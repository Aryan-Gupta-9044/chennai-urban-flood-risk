#!/usr/bin/env python
"""Module B - DEM (Copernicus GLO-30) -> elevation + slope on the 30 m master grid."""
import math
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from rasterio.merge import merge
from rasterio.warp import Resampling
from src.utils import status, paths, net
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.raster_io import read_bounds
from src.geospatial.terrain import slope_degrees
from src.geospatial.study_area import load_study_area, bounds_wgs84, master_grid
from src.visualization import plots

ND = -9999.0


def tile_name(lat, lon):
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00"


def main():
    t0 = time.time()
    log = get_logger("B_dem")
    cfg = load_settings()
    sa_wgs, sa_utm, _ = load_study_area()
    grid = master_grid()
    minx, miny, maxx, maxy = bounds_wgs84(pad=0.01)
    raw_dir = paths.DATA_RAW / "dem"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_out = raw_dir / f"copdem30_{minx:.2f}_{miny:.2f}_{maxx:.2f}_{maxy:.2f}.tif"
    kind, source = status.REAL, cfg["dem"]["name"]
    arr = tr = crs = nd = None

    ext = sorted((paths.DATA_EXT / "dem").glob("*.tif*"))
    if ext:
        r = read_bounds(ext[0], (minx, miny, maxx, maxy))
        if r is not None:
            arr, tr, crs, nd = r
            kind, source = paths.external_kind(), f"data/external/dem/{ext[0].name}"
            log.info("using user-supplied DEM %s", ext[0].name)
    if arr is None and raw_out.exists():
        arr, tr, crs, nd = read_bounds(raw_out, (minx, miny, maxx, maxy))
        log.info("using cached raw DEM subset %s", raw_out.name)
    if arr is None:
        parts, errs = [], []
        for lat in range(math.floor(miny), math.floor(maxy) + 1):
            for lon in range(math.floor(minx), math.floor(maxx) + 1):
                tn = tile_name(lat, lon)
                url = cfg["dem"]["url_template"].format(tile=tn)
                part = raw_dir / f"copdem30_{tn}_subset.tif"
                try:
                    r = read_bounds(url, (minx, miny, maxx, maxy))
                except Exception as e:
                    log.warning("remote read failed for %s (%s); trying full-tile download", tn, str(e)[:120])
                    try:
                        full = net.download(url, raw_dir / f"copdem30_{tn}_full.tif", log=log)
                        r = read_bounds(full, (minx, miny, maxx, maxy))
                    except Exception as e2:
                        errs.append(f"{tn}: {str(e2)[:150]}")
                        continue
                if r is None:
                    continue
                a, t, c, n = r
                with rasterio.open(part, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=1,
                                   dtype=a.dtype, crs=c, transform=t, nodata=n, compress="deflate") as d:
                    d.write(a, 1)
                parts.append(part)
        if not parts:
            msg = "DEM not obtained: " + (" | ".join(errs) or "no tile covered the study area")
            log.error(msg)
            status.record("B", status.BLOCKED, msg,
                          requirements=["Run with internet access (Copernicus GLO-30 on AWS Open Data), or place a DEM "
                                        "GeoTIFF covering Chennai in data/external/dem/ (e.g. from OpenTopography)."],
                          seconds=time.time() - t0)
            return
        srcs = [rasterio.open(p) for p in parts]
        try:
            arr_m, tr = merge(srcs)
            crs, nd = srcs[0].crs, srcs[0].nodata
            arr = arr_m[0]
            with rasterio.open(raw_out, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                               dtype=arr.dtype, crs=crs, transform=tr, nodata=nd, compress="deflate") as d:
                d.write(arr, 1)
        finally:
            for s in srcs:
                s.close()
        log.info("raw DEM subset saved: %s", paths.rel(raw_out))

    dem = G.to_grid(arr.astype("float32"), tr, crs, grid, Resampling.bilinear, src_nodata=nd, dst_nodata=ND)
    slope = slope_degrees(dem, grid.res, ND)          # slope computed before masking (keeps edge neighbours)
    inside = G.inside_mask(grid, sa_utm.geometry)
    dem = np.where(inside & (dem != ND), dem, ND).astype("float32")
    slope = np.where(inside & (dem != ND), slope, ND).astype("float32")
    valid = dem != ND
    if valid.sum() == 0:
        status.record("B", status.BLOCKED, "DEM contains no valid cells inside the study area.",
                      seconds=time.time() - t0)
        return
    warn = []
    if dem[valid].max() > 300 or dem[valid].min() < -30:  # V2: plausibility check (Chennai is low-lying, roughly 0-100 m)
        warn.append(f"implausible elevation range {dem[valid].min():.0f}..{dem[valid].max():.0f} m for Chennai - check source/datum")
        log.warning(warn[-1])
    f_el = paths.DATA_PROC / "dem_elevation_utm44n_30m.tif"
    f_sl = paths.DATA_PROC / "slope_deg_utm44n_30m.tif"
    G.write_raster(f_el, dem, grid, ND, "elevation_m")
    G.write_raster(f_sl, slope, grid, ND, "slope_deg")
    stats = pd.DataFrame([
        {"layer": "elevation_m", "min": dem[valid].min(), "mean": dem[valid].mean(), "median": np.median(dem[valid]),
         "max": dem[valid].max(), "valid_cells": int(valid.sum())},
        {"layer": "slope_deg", "min": slope[valid & (slope != ND)].min(), "mean": slope[valid & (slope != ND)].mean(),
         "median": np.median(slope[valid & (slope != ND)]), "max": slope[valid & (slope != ND)].max(),
         "valid_cells": int((valid & (slope != ND)).sum())}]).round(3)
    stats.to_csv(paths.OUT_TAB / "dem_statistics.csv", index=False)
    w = None
    if (paths.DATA_PROC / "wards_utm44n.geojson").exists():
        import geopandas as gpd
        w = gpd.read_file(paths.DATA_PROC / "wards_utm44n.geojson")
    plots.raster_map(dem, grid, sa_utm, f"Elevation (m) - {source}", paths.OUT_FIG / "elevation_map.png", ND,
                     "terrain", "Elevation (m)", wards_utm=w)
    plots.raster_map(slope, grid, sa_utm, "Slope (degrees)", paths.OUT_FIG / "slope_map.png", ND, "magma",
                     "Slope (deg)", vmin=0, vmax=np.percentile(slope[valid & (slope != ND)], 99))
    status.record("B", status.PARTIAL if warn else status.COMPLETED,
                  ("WARNING: " + "; ".join(warn) + ". " if warn else "") + f"Elevation {dem[valid].min():.1f}..{dem[valid].max():.1f} m on {grid.res:.0f} m grid. Source: {source}. "
                  + ("Copernicus GLO-30 is a surface model (includes buildings/trees), so urban micro-relief is approximate."
                     if kind == status.REAL else "Check the vertical datum and whether it is a surface or terrain model."),
                  files=["data/processed/dem_elevation_utm44n_30m.tif", "data/processed/slope_deg_utm44n_30m.tif",
                         "outputs/figures/elevation_map.png", "outputs/figures/slope_map.png",
                         "outputs/tables/dem_statistics.csv", paths.rel(raw_out)],
                  datasets=[{"name": "DEM", "kind": kind, "source": source, "path": paths.rel(raw_out) if kind == status.REAL else source}],
                  requirements=["Flow accumulation / TWI need hydrological conditioning (planned next module)."],
                  seconds=time.time() - t0)


if __name__ == "__main__":
    main()
