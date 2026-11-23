#!/usr/bin/env python
"""Module D - ESA WorldCover 2021 land cover (10 m) -> 30 m class map + built-up fraction."""
import math
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import grid as G
from src.geospatial.raster_io import read_bounds
from src.geospatial.study_area import load_study_area, bounds_wgs84, master_grid
from src.visualization import plots

CLASSES = {10: ("Tree cover", "#006400"), 20: ("Shrubland", "#ffbb22"), 30: ("Grassland", "#ffff4c"),
           40: ("Cropland", "#f096ff"), 50: ("Built-up", "#fa0000"), 60: ("Bare / sparse", "#b4b4b4"),
           70: ("Snow / ice", "#f0f0f0"), 80: ("Permanent water", "#0064c8"), 90: ("Herbaceous wetland", "#0096a0"),
           95: ("Mangroves", "#00cf75"), 100: ("Moss / lichen", "#fae6a0")}
ND = 255


def tile(lat, lon):
    la, lo = int(math.floor(lat / 3) * 3), int(math.floor(lon / 3) * 3)
    return f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"


def main():
    t0 = time.time()
    log = get_logger("D_landcover")
    cfg = load_settings()
    sa_wgs, sa_utm, _ = load_study_area()
    grid = master_grid()
    minx, miny, maxx, maxy = bounds_wgs84(pad=0.005)
    raw_dir = paths.DATA_RAW / "landcover"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_out = raw_dir / f"worldcover2021_{minx:.3f}_{miny:.3f}_{maxx:.3f}_{maxy:.3f}.tif"
    kind, source = status.REAL, cfg["landcover"]["name"]
    r = None
    ext = sorted((paths.DATA_EXT / "landcover").glob("*.tif*"))
    if ext:
        r = read_bounds(ext[0], (minx, miny, maxx, maxy))
        kind, source = paths.external_kind(), f"data/external/landcover/{ext[0].name}"
    if r is None and raw_out.exists():
        r = read_bounds(raw_out, (minx, miny, maxx, maxy))
        log.info("using cached raw land-cover subset")
    if r is None:
        tiles = {tile(la, lo) for la in (miny, maxy) for lo in (minx, maxx)}
        if len(tiles) != 1:
            status.record("D", status.BLOCKED, f"Study area spans several WorldCover tiles {sorted(tiles)}; "
                          "multi-tile mosaic not implemented. Place a clipped GeoTIFF in data/external/landcover/.",
                          seconds=time.time() - t0)
            return
        tn = tiles.pop()
        url = cfg["landcover"]["url_template"].format(tile=tn)
        try:
            log.info("reading window from %s", url)
            r = read_bounds(url, (minx, miny, maxx, maxy))
            if r is not None:
                a, t, c, n = r
                with rasterio.open(raw_out, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=1,
                                   dtype=a.dtype, crs=c, transform=t, nodata=n, compress="deflate") as d:
                    d.write(a, 1)
        except Exception as e:
            status.record("D", status.BLOCKED, f"WorldCover not obtained: {str(e)[:250]}",
                          requirements=["Run with internet access (AWS Open Data), or place a WorldCover GeoTIFF "
                                        "clipped to Chennai in data/external/landcover/."],
                          seconds=time.time() - t0)
            log.error("failed: %s", e)
            return
    if r is None:
        status.record("D", status.BLOCKED, "WorldCover tile does not overlap the study area.", seconds=time.time() - t0)
        return
    a, t, c, n = r
    lc = G.to_grid(a, t, c, grid, Resampling.mode, src_nodata=n, dst_nodata=ND, dtype="uint8")
    built = G.to_grid((a == 50).astype("float32"), t, c, grid, Resampling.average, dst_nodata=-1.0)
    inside = G.inside_mask(grid, sa_utm.geometry)
    lc = np.where(inside, lc, ND).astype("uint8")
    built = np.where(inside & (lc != ND), built, -9999.0).astype("float32")
    G.write_raster(paths.DATA_PROC / "landcover_class_utm44n_30m.tif", lc, grid, ND, "worldcover_class", "uint8")
    G.write_raster(paths.DATA_PROC / "builtup_fraction_utm44n_30m.tif", built, grid, -9999.0, "builtup_fraction")
    vals, cnt = np.unique(lc[lc != ND], return_counts=True)
    area = cnt * (grid.res ** 2) / 1e6
    df = pd.DataFrame({"class_code": vals, "class": [CLASSES.get(int(v), ("Unknown",))[0] for v in vals],
                       "area_km2": area.round(2), "percent": (100 * cnt / cnt.sum()).round(2)})
    df.to_csv(paths.OUT_TAB / "landcover_statistics.csv", index=False)
    plots.categorical_map(lc, grid, sa_utm, CLASSES, f"Land cover (30 m, majority of 10 m cells)\n{source}",
                          paths.OUT_FIG / "landcover_map.png")
    status.record("D", status.COMPLETED,
                  "Built-up share %.1f%%. Class map = majority of 10 m WorldCover cells per 30 m cell; "
                  "built-up fraction layer is an imperviousness PROXY." % df.loc[df.class_code == 50, "percent"].sum(),
                  files=["data/processed/landcover_class_utm44n_30m.tif", "data/processed/builtup_fraction_utm44n_30m.tif",
                         "outputs/figures/landcover_map.png", "outputs/tables/landcover_statistics.csv", paths.rel(raw_out)],
                  datasets=[{"name": "Land cover", "kind": kind, "source": source, "path": paths.rel(raw_out) if kind == status.REAL else source}],
                  seconds=time.time() - t0)


if __name__ == "__main__":
    main()
