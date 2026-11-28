"""Exposure inside SUS-1 high-susceptibility cells (read-only on SUS-1).

Uses outputs/susceptibility_v1/rasters/susceptibility_percentile.tif (0-100 mid-rank percentile within
the scored domain) and domain_class.tif (1 scored, 2 water-signature excluded, 3 missing, 255 outside).
Excluded / missing / outside cells are NOT ASSESSED - never counted as low susceptibility.
Susceptibility is relative terrain predisposition, not hazard; results are 'assets in high-susceptibility
cells', not 'assets at flood risk'.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import ANALYSIS_CRS

SUS1_GRID = {"crs": "EPSG:32644", "transform": (30.0, 0.0, 406020.0, 0.0, -30.0, 1463310.0), "shape": (1416, 726)}


def read_sus1(pct_path, dom_path):
    import rasterio
    with rasterio.open(pct_path) as d:
        pct, tr, crs, shp, nd = d.read(1).astype(float), d.transform, d.crs, d.shape, d.nodata
    with rasterio.open(dom_path) as d:
        dom, tr2 = d.read(1), d.transform
    if str(crs) != SUS1_GRID["crs"] or tuple(tr)[:6] != SUS1_GRID["transform"] or shp != SUS1_GRID["shape"] or tuple(tr2)[:6] != SUS1_GRID["transform"]:
        raise SystemExit(f"STOP: SUS-1 rasters are not on the accepted master grid ({crs}, {tuple(tr)[:6]}, {shp})")
    pct = np.where((dom == 1) & (pct != nd) & np.isfinite(pct), pct, np.nan)
    return pct, dom, tr


def overlay(pct, dom, tr, wards, facilities, worldpop=None, threshold=90.0):
    """Per-ward: assessed share, share of assessed area with percentile >= threshold, facilities and WorldPop people in those cells."""
    from rasterio.features import rasterize
    ids = rasterize(((g, int(w)) for g, w in zip(wards.to_crs(ANALYSIS_CRS).geometry, wards.ward_no)), out_shape=pct.shape, transform=tr, fill=0, dtype="int32")
    high = np.isfinite(pct) & (pct >= threshold)
    rows = []
    for w in wards.ward_no:
        m = ids == w
        n, ns = int(m.sum()), int((m & np.isfinite(pct)).sum())
        rows.append({"ward_no": int(w), "cells_in_ward_on_grid": n, "cells_assessed": ns,
                     "cells_not_assessed": int((m & (dom != 1) & (dom != 255)).sum()), "cells_outside_aoi": int((m & (dom == 255)).sum()),
                     "assessed_share": ns / n if n else np.nan,
                     f"share_assessed_area_pct_ge_{int(threshold)}": float((m & high).sum() / ns) if ns else np.nan})
    t = pd.DataFrame(rows)
    f = facilities.to_crs(ANALYSIS_CRS)
    col = np.floor((f.geometry.x - tr.c) / tr.a).astype(int)
    row = np.floor((f.geometry.y - tr.f) / tr.e).astype(int)
    inside = (row >= 0) & (row < pct.shape[0]) & (col >= 0) & (col < pct.shape[1])
    f["sus1_cell_state"] = "outside_grid"
    f.loc[inside, "sus1_cell_state"] = np.where(high[row[inside], col[inside]], "high",
                                                 np.where(np.isfinite(pct[row[inside], col[inside]]), "assessed_not_high", "not_assessed"))
    fc = f[f.sus1_cell_state == "high"].groupby("ward_no").size().rename(f"facilities_in_pct_ge_{int(threshold)}")
    t = t.merge(fc.reset_index(), on="ward_no", how="left").fillna({f"facilities_in_pct_ge_{int(threshold)}": 0})
    if worldpop is not None:
        a, wtr, wnd = worldpop
        # each 30 m high cell transfers (30*30)/(cell area of WorldPop) of its WorldPop cell's people; uniform density within a 100 m cell is ASSUMED
        rr, cc = np.nonzero(high)
        xs, ys = tr.c + (cc + 0.5) * tr.a, tr.f + (rr + 0.5) * tr.e
        wc = np.floor((xs - wtr.c) / wtr.a).astype(int)
        wr = np.floor((ys - wtr.f) / wtr.e).astype(int)
        ok = (wr >= 0) & (wr < a.shape[0]) & (wc >= 0) & (wc < a.shape[1])
        v = np.zeros(len(rr))
        vv = a[wr[ok], wc[ok]]
        good = (vv != wnd) & np.isfinite(vv)
        v[np.flatnonzero(ok)[good]] = vv[good] * (abs(tr.a * tr.e) / abs(wtr.a * wtr.e))
        wid = ids[rr, cc]
        s = pd.Series(v).groupby(wid).sum()
        t[f"wp_people_in_pct_ge_{int(threshold)}_approx"] = t.ward_no.map(s).astype(float)
    return t, f
