#!/usr/bin/env python
"""Compare a detected S1 flood raster with a user-supplied REFERENCE raster (1 = flood, 0 = not).
Reports AGREEMENT metrics (IoU/F1/precision/recall), clearly not accuracy.
Usage: python scripts/compare_reference.py --event 2021_nov --reference path\\to\\reference.tif --name "ALOS-2 8 Nov 2021 (digitised)"
The reference must cover the study area; it is resampled (nearest) to the master grid."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from rasterio.warp import Resampling
from src.utils import paths
from src.geospatial import grid as G
from src.geospatial.study_area import load_study_area, master_grid
from src.flood_detection.agreement import agreement


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--name", required=True, help="citation/description of the reference product")
    a = ap.parse_args()
    _, sa_utm, _ = load_study_area()
    grid = master_grid()
    det, nd, _, _ = G.read_raster(paths.DATA_PROC / "s1" / f"flood_{a.event}_utm44n_30m.tif")
    with rasterio.open(a.reference) as ds:
        ref = G.to_grid(ds.read(1).astype("float32"), ds.transform, ds.crs, grid, Resampling.nearest,
                        src_nodata=ds.nodata, dst_nodata=255, dtype="uint8")
    valid = G.inside_mask(grid, sa_utm.geometry) & (det != 255) & (ref != 255)
    res = agreement(det, ref, valid)
    res.update(event=a.event, reference=a.name, valid_cells=int(valid.sum()))
    out = paths.OUT_TAB / f"agreement_{a.event}.json"
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
