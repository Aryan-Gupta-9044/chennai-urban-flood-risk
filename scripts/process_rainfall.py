#!/usr/bin/env python
"""Module C - CHIRPS daily rainfall: small sample around the Dec 2023 event.
V2.3: missing days are never zero-filled; totals are strict; native-resolution raster is written; the 30 m file is a labelled nearest-neighbour copy.
For the 2015 event use scripts/rainfall_workflow.py (source-agnostic) once a source is confirmed."""
import gzip
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from rasterio.warp import Resampling
from src.utils import status, paths, net
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.raster_io import read_bounds
from src.geospatial.study_area import load_study_area, bounds_wgs84, master_grid
from src.visualization import plots
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ND = -9999.0


def daterange(a, b):
    d = date.fromisoformat(a)
    e = date.fromisoformat(b)
    while d <= e:
        yield d
        d += timedelta(days=1)


def main():
    t0 = time.time()
    log = get_logger("C_rainfall")
    cfg = load_settings()
    rc = cfg["rainfall"]
    sa_wgs, sa_utm, _ = load_study_area()
    grid = master_grid()
    bb = bounds_wgs84(pad=0.1)
    raw_dir = paths.DATA_RAW / "rainfall"
    raw_dir.mkdir(parents=True, exist_ok=True)
    days, errors, fails_in_row = {}, [], 0
    for d in daterange(rc["sample_start"], rc["sample_end"]):
        tif = raw_dir / f"chirps-v2.0.{d:%Y.%m.%d}.tif"
        gz = raw_dir / (tif.name + ".gz")
        try:
            if not tif.exists():
                if not gz.exists():
                    url = rc["url_template"].format(year=d.year, month=d.month, day=d.day)
                    net.download(url, gz, retries=2, log=log)
                with gzip.open(gz, "rb") as fi, open(tif, "wb") as fo:
                    shutil.copyfileobj(fi, fo)
            r = read_bounds(tif, bb)
            if r is None:
                raise RuntimeError("no overlap")
            a, t, c, n = r
            a = a.astype("float32")
            a[(a == (n if n is not None else -9999)) | (a < 0)] = np.nan
            days[d] = (a, t, c)
            fails_in_row = 0
        except Exception as e:
            errors.append(f"{d}: {str(e)[:140]}")
            fails_in_row += 1
            if fails_in_row >= 2 and not days:
                log.error("two consecutive failures with no data - assuming no network; stopping")
                break
    n_req = (date.fromisoformat(rc["sample_end"]) - date.fromisoformat(rc["sample_start"])).days + 1
    if not days:
        msg = "No CHIRPS rainfall obtained: " + (" | ".join(errors[:3]) or "unknown")
        log.error(msg)
        status.record("C", status.BLOCKED, msg,
                      requirements=["Run with internet access (data.chc.ucsb.edu), or place daily files named "
                                    "chirps-v2.0.YYYY.MM.DD.tif(.gz) in data/raw/rainfall/."],
                      seconds=time.time() - t0)
        return

    # V2.3 (M3 audit): missing/invalid days are NEVER treated as 0 mm; statistics are AOI-area-weighted; totals are strict.
    from src.geospatial import rainfall as R
    import geopandas as gpd
    aoi = sa_wgs.geometry.union_all() if hasattr(sa_wgs.geometry, "union_all") else sa_wgs.unary_union
    d0 = sorted(days)[0]
    a0, t_nat, c_nat = days[d0]
    R.check_same_grid([(t, a.shape, c) for a, t, c in days.values()])
    wts = R.cell_weights(t_nat, a0.shape, gpd.GeoSeries([aoi], crs=4326).to_crs(c_nat).iloc[0])
    rows = []
    for d in daterange(rc["sample_start"], rc["sample_end"]):
        if d not in days:
            rows.append({"date": d.isoformat(), "status": "MISSING", "mean_mm": None, "max_mm": None, "cells": 0, "aoi_valid_coverage": 0.0})
            continue
        mm, _ = R.clean_day(days[d][0], "mm")
        st = R.weighted_stats(mm, wts)
        rows.append({"date": d.isoformat(), "status": R.classify_day(mm, wts), "mean_mm": round(st["mean_mm"], 2), "max_mm": round(st["max_mm"], 2),
                     "cells": st["cells_valid"], "aoi_valid_coverage": round(st["coverage"], 3)})
    df = pd.DataFrame(rows)
    df.to_csv(paths.OUT_TAB / "rainfall_daily_stats.csv", index=False)
    ok_days = {d: R.clean_day(days[d][0], "mm")[0] for d in days}
    ok_days = {d: (m if R.classify_day(m, wts) == "OK" else None) for d, m in ok_days.items()}

    ev_all = daterange(rc["event_start"], rc["event_end"])
    miss_ev = [d for d in ev_all if ok_days.get(d) is None]
    f_tot = f_nat = None
    if not miss_ev:
        tot, _ = R.strict_total([ok_days[d] for d in ev_all])
        f_nat = paths.DATA_PROC / "rainfall_event_total_mm_native_chirps.tif"
        import rasterio
        with rasterio.open(f_nat, "w", driver="GTiff", height=tot.shape[0], width=tot.shape[1], count=1, dtype="float32", crs=c_nat,
                           transform=t_nat, nodata=ND, compress="deflate") as dst:
            dst.write(np.where(np.isfinite(tot), tot, ND).astype("float32"), 1)
            dst.set_band_description(1, "CHIRPS event total mm, NATIVE 0.05 deg grid")
        tot_g = G.to_grid(np.where(np.isfinite(tot), tot, ND), t_nat, c_nat, grid, Resampling.nearest, src_nodata=ND, dst_nodata=ND)
        f_tot = paths.DATA_PROC / "rainfall_event_total_mm_utm44n_30m.tif"
        G.write_raster(f_tot, tot_g, grid, ND, "RESAMPLED nearest from native 0.05 deg CHIRPS: contains NO 30 m information")
        plots.raster_map(tot_g, grid, sa_utm, f"CHIRPS rainfall {rc['event_start']} to {rc['event_end']} (mm)\n"
                         "0.05 deg cells RESAMPLED to the 30 m grid (nearest): no 30 m information", paths.OUT_FIG / "rainfall_event_map.png",
                         ND, "Blues", "Total rainfall (mm)")
    else:
        log.warning("event total NOT computed: %d of %d event days missing/unusable (%s). Missing days are not treated as zero.",
                    len(miss_ev), len(ev_all), ", ".join(d.isoformat() for d in miss_ev[:5]))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(df["date"], df["mean_mm"].astype(float), color="#2b7bba")
    ax.set_ylabel("AOI-weighted mean CHIRPS rainfall (mm/day); gaps = missing days")
    ax.set_title("CHIRPS daily rainfall sample")
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(paths.OUT_FIG / "rainfall_daily_bar.png", dpi=200)
    plt.close(fig)
    state = status.COMPLETED if (len(days) == n_req and not miss_ev and (df["status"] == "OK").all()) else status.PARTIAL
    msg = f"{len(days)}/{n_req} days obtained ({rc['sample_start']}..{rc['sample_end']}); event total " + \
          ("computed from all event days. " if not miss_ev else f"NOT computed ({len(miss_ev)} event days missing/unusable). ") + \
          "CHIRPS is ~5 km resolution, so it cannot resolve neighbourhood-scale rainfall (30 m raster is a nearest-neighbour copy). " + \
          ("Failed days: " + "; ".join(errors[:3]) if errors else "")
    files = ["outputs/tables/rainfall_daily_stats.csv", "outputs/figures/rainfall_daily_bar.png"]
    if f_tot:
        files += [paths.rel(f_nat), paths.rel(f_tot), "outputs/figures/rainfall_event_map.png"]
    status.record("C", state, msg, files=files,
                  datasets=[{"name": "CHIRPS daily rainfall (sample)", "kind": ("SIMULATED" if paths.external_kind() == "SIMULATED" else status.SAMPLE), "source": rc["name"],
                             "path": "data/raw/rainfall/"}],
                  requirements=["Longer rainfall record (years) is needed for the LSTM rainfall-trigger module."],
                  seconds=time.time() - t0)


if __name__ == "__main__":
    main()
