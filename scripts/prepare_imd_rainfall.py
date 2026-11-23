#!/usr/bin/env python
"""Module IMD (V2.3 demo) - inspect the preserved IMD yearly file and convert it to NATIVE-resolution daily GeoTIFFs (no resampling, no zero-filling).
Configured from the file's own metadata; refuses to guess dates, units or orientation. The original file is only read.
Usage:  .\\.venv\\Scripts\\python scripts\\prepare_imd_rainfall.py --year 2015
Options: --raw PATH  --start/--end (default: context window of config/rainfall_events.json)  --all-days  --registration centre|corner
Outputs: data\\external\\rainfall\\imd_gridded_daily\\daily\\YYYYMMDD.tif, source.json, outputs\\reports\\imd_inspection_<year>.md, outputs\\tables\\imd_conversion_<year>.csv"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial import imd, rainfall as R

BASE = paths.DATA_EXT / "rainfall" / "imd_gridded_daily"
ND = -9999.0
MM_UNITS = {"mm", "millimeter", "millimeters", "millimetre", "millimetres", "mm/day", "mm/d", "kg m-2", "kg/m2"}


def fail(log, msg, t0, **kw):
    log.error(msg); status.record("IMD", status.BLOCKED, msg, seconds=time.time() - t0, **kw); return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2015)
    ap.add_argument("--raw", default="")
    ap.add_argument("--start", default=""); ap.add_argument("--end", default="")
    ap.add_argument("--all-days", action="store_true")
    ap.add_argument("--registration", choices=["centre", "corner"], default="centre", help="are grid coordinates cell centres? (PROVISIONAL: centre)")
    ap.add_argument("--base-dir", default=str(BASE)); ap.add_argument("--outputs-dir", default=str(paths.ROOT / "outputs"))
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("IMD_prepare"); paths.ensure_dirs()
    base, odir = Path(a.base_dir), Path(a.outputs_dir)
    (odir / "reports").mkdir(parents=True, exist_ok=True); (odir / "tables").mkdir(parents=True, exist_ok=True)
    raw = Path(a.raw) if a.raw else next((p for p in [base / "raw" / f"imd_rain_0p25_{a.year}.nc", base / "raw" / f"imd_rain_0p25_{a.year}.grd"] if p.exists()), None)
    if raw is None or not raw.exists():
        return fail(log, f"no raw IMD file for {a.year} in {base / 'raw'}: run scripts\\fetch_imd_rainfall.py first", t0, requirements=["python scripts/fetch_imd_rainfall.py"])
    manifest = next(iter(sorted(raw.parent.glob(raw.name + ".manifest.json"))), None)
    mani = json.loads(manifest.read_text(encoding="utf-8")) if manifest else {}
    ev = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"]["2015_nov_dec"]
    d0 = date.fromisoformat(a.start or ev["context_window"][0]); d1 = date.fromisoformat(a.end or ev["context_window"][1])
    Q = []          # inspection lines

    # ------------------------------------------------------------ read + inspect
    if raw.suffix.lower() == ".grd":
        cube, info = imd.read_grd(raw, a.year)
        n = cube.shape[0]; dates = [date(a.year, 1, 1) + timedelta(days=i) for i in range(n)]
        lat = imd.LAT0 + imd.RES * np.arange(imd.NY); lon = imd.LON0 + imd.RES * np.arange(imd.NX)
        unit, unit_src, time_src = "mm", "IMD page statement (binary file has no metadata)", "IMD page: daily records from 1 Jan (file has no timestamps)"
        flip_needed = True; attrs = {}; Q += [f"Format: binary GrADS-style .grd, byte order {info['byte_order']}, {100 * info['sane_fraction']:.3f}% sane values", f"Records: {n}"]
    else:
        try:
            vs, ga, backend = imd.open_nc(raw)
        except RuntimeError as e:
            return fail(log, str(e), t0)
        inf = imd.inspect_nc(vs, ga)
        Q += [f"Format: NetCDF read with {backend}", f"Global attributes: {json.dumps({k: str(v)[:100] for k, v in ga.items()})}"]
        for n_, v in inf["variables"].items():
            Q.append(f"- variable `{n_}` dims={v['dims']} shape={v['shape']} dtype={v['dtype']} attrs={json.dumps({k: str(x)[:80] for k, x in v['attrs'].items()})}")
        miss = [k for k in ("rain_var", "time_var", "lat_var", "lon_var") if not inf[k]]
        if miss:
            (odir / "reports" / f"imd_inspection_{a.year}.md").write_text("# IMD NetCDF inspection\n\n" + "\n".join(Q), encoding="utf-8")
            return fail(log, f"cannot identify {miss} in the NetCDF; see outputs/reports/imd_inspection_{a.year}.md and configure manually (nothing was guessed)", t0)
        rv = vs[inf["rain_var"]]
        dims = rv["dims"]
        tdim, ydim, xdim = (next(i for i, dn in enumerate(dims) if dn == vs[inf[k]]["dims"][0]) for k in ("time_var", "lat_var", "lon_var"))
        data = np.transpose(rv["data"](), (tdim, ydim, xdim))
        attrs = rv["attrs"]
        cube, nbad_attr = imd.clean_values(data, attrs)
        lat = np.asarray(vs[inf["lat_var"]]["data"](), dtype="float64"); lon = np.asarray(vs[inf["lon_var"]]["data"](), dtype="float64")
        tv = vs[inf["time_var"]]
        try:
            dates, _ = imd.decode_time(tv["data"](), tv["attrs"].get("units"))
        except ValueError as e:
            return fail(log, f"time axis: {e}", t0)
        unit = str(attrs.get("units", "")).strip()
        unit_src = "NetCDF attribute" if unit else "MISSING in file; IMD page says mm (assumed)"
        unit = unit or "mm"
        time_src = f"NetCDF `{inf['time_var']}` units '{tv['attrs'].get('units')}'"
        Q += [f"Rain variable `{inf['rain_var']}`, axes (time,lat,lon) = dims {dims}; time `{inf['time_var']}`, lat `{inf['lat_var']}`, lon `{inf['lon_var']}`", f"Values flagged missing by attributes/UNDEF: {nbad_attr}"]
        info = {}
    if unit.lower() not in MM_UNITS:
        return fail(log, f"rainfall unit '{unit}' is not recognised as millimetres: refusing to guess", t0)
    # ------------------------------------------------------------ date + grid verification
    problems = []
    exp_n = 366 if imd.is_leap(a.year) else 365
    if len(dates) != exp_n: problems.append(f"{len(dates)} time records, expected {exp_n}")
    if dates[0] != date(a.year, 1, 1) or dates[-1] != date(a.year, 12, 31): problems.append(f"time axis spans {dates[0]}..{dates[-1]}")
    if any((b - a_).days != 1 for a_, b in zip(dates, dates[1:])): problems.append("time axis is not strictly daily/continuous")
    try:
        asc, tr = imd.grid_from_coords(lat, lon, a.registration)
    except ValueError as e:
        problems.append(str(e)); asc, tr = True, None
    if cube.shape[1:] != (imd.NY, imd.NX): problems.append(f"data grid {cube.shape[1:]} != {(imd.NY, imd.NX)}")
    if problems:
        return fail(log, "verification failed: " + " | ".join(problems), t0)
    if asc:
        cube = cube[:, ::-1, :]
    Q += [f"Grid: {imd.NY} x {imd.NX}, lat {lat.min()}..{lat.max()} ({'ascending, flipped to north-up' if asc else 'descending'}), lon {lon.min()}..{lon.max()}, spacing 0.25 deg",
          f"Registration: coordinates treated as cell {a.registration}s (PROVISIONAL: IMD says 'grid points'; transform origin {tr.c}, {tr.f})",
          f"Time: {len(dates)} daily records {dates[0]}..{dates[-1]} ({time_src}); continuous: yes", f"Units: {unit} ({unit_src})"]
    # ------------------------------------------------------------ AOI cells
    aoi_cells, aoi_b = [], None
    try:
        from src.geospatial.study_area import bounds_wgs84
        aoi_b = bounds_wgs84(); aoi_cells = imd.cells_for_bounds(tr, cube.shape[1:], aoi_b)
    except FileNotFoundError:
        Q.append("Study area not found: AOI cell check skipped")
    if aoi_cells:
        Q.append(f"Study-area bounds {tuple(round(x, 4) for x in aoi_b)} overlap {len(aoi_cells)} native cell(s): " + "; ".join(f"[r{i} c{j} centre {x:.3f}E {y:.3f}N]" for i, j, x, y in aoi_cells))
        for i, j, x, y in aoi_cells:
            s = cube[:, i, j]; Q.append(f"  cell r{i} c{j}: {int(np.isnan(s).sum())} of {len(s)} days NaN (all-year), min {np.nanmin(s) if np.isfinite(s).any() else 'n/a'}, max {np.nanmax(s) if np.isfinite(s).any() else 'n/a'}")
    # ------------------------------------------------------------ write daily GeoTIFFs
    sel = [(i, d) for i, d in enumerate(dates) if a.all_days or d0 <= d <= d1]
    if not sel:
        return fail(log, f"no dates in {d0}..{d1} within the file", t0)
    out = base / "daily"; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, d in sel:
        arr = cube[i]
        fin = np.isfinite(arr)
        p = out / f"{d:%Y%m%d}.tif"
        with rasterio.open(p, "w", driver="GTiff", height=imd.NY, width=imd.NX, count=1, dtype="float32", crs=CRS.from_epsg(4326), transform=tr, nodata=ND, compress="deflate") as ds:
            ds.write(np.where(fin, arr, ND).astype("float32"), 1)
            ds.set_band_description(1, f"IMD 0.25 deg daily rainfall mm, record date {d} (day definition PROVISIONAL)")
            ds.update_tags(source=str(raw.name), day_definition="PROVISIONAL: 24h ending 08:30 IST on labelled date", native_resolution="0.25 deg")
        rows.append({"date": d.isoformat(), "file": p.name, "cells": int(arr.size), "nan_cells": int((~fin).sum()), "negative_cells": int((arr[fin] < 0).sum()),
                     "over_1000mm_cells": int((arr[fin] > 1000).sum()), "min_mm": float(np.nanmin(arr)) if fin.any() else None,
                     "max_mm": float(np.nanmax(arr)) if fin.any() else None, "mean_mm": float(np.nanmean(arr)) if fin.any() else None})
        log.info("%s: %d NaN, %d negative, max %s", d, rows[-1]["nan_cells"], rows[-1]["negative_cells"], rows[-1]["max_mm"])
    df = pd.DataFrame(rows); df.to_csv(odir / "tables" / f"imd_conversion_{a.year}.csv", index=False)
    # read-back check against the in-memory cube for AOI cells (automated stand-in for manual inspection)
    rb = []
    for i, d in [sel[0], sel[len(sel) // 2], sel[-1]]:
        with rasterio.open(out / f"{d:%Y%m%d}.tif") as ds:
            a2 = ds.read(1)
            assert ds.transform == tr and ds.crs.to_epsg() == 4326
        for (ri, cj, x, y) in (aoi_cells[:3] or [(0, 0, 0, 0)]):
            v_cube, v_tif = float(cube[i, ri, cj]), float(a2[ri, cj])
            ok = (np.isnan(v_cube) and v_tif == ND) or (abs(v_cube - v_tif) < 1e-4)
            rb.append(f"{d} cell r{ri} c{cj}: cube {v_cube} vs GeoTIFF {v_tif} -> {'match' if ok else 'MISMATCH'}")
            if not ok:
                return fail(log, "GeoTIFF read-back mismatch: " + rb[-1], t0)
    # ------------------------------------------------------------ source.json for the workflow
    src = {"source_id": "imd_gridded_daily", "name": "IMD gridded daily rainfall 0.25 deg (Pai et al. 2014)", "version": f"yearly file {a.year}, as retrieved (sha256 {mani.get('sha256', 'unknown')[:16]})",
           "product_type": "gauge-gridded", "unit": "mm", "accumulation_hours": None, "day_definition": imd.DAY_DEFINITION, "file_pattern": "daily/{date:%Y%m%d}.tif",
           "expected_crs": "EPSG:4326", "nodata": ND, "native_resolution": "0.25 deg", "obtained_from": mani.get("source_url", "UNKNOWN (no manifest)"),
           "obtained_on": str(mani.get("retrieved_utc", "UNKNOWN"))[:10], "licence_note": "UNCONFIRMED: check IMD data-use terms; cite Pai et al. (2014)",
           "grid_registration": f"{a.registration} (PROVISIONAL)", "raw_file": paths.rel(raw), "demo_status": "DEMONSTRATION VERSION; not independently validated"}
    (base / "source.json").write_text(json.dumps(src, indent=2), encoding="utf-8")
    neg = int(df["negative_cells"].sum()); over = int(df["over_1000mm_cells"].sum())
    L = [f"# IMD rainfall inspection and conversion - {a.year}", "", "**Native 0.25 deg conversion only: no resampling, no zero-filling. Demonstration version; day definition PROVISIONAL; not validated.**", "",
         f"- Raw file: `{paths.rel(raw)}` (preserved, read-only here); manifest: `{manifest.name if manifest else 'NONE'}`; sha256 `{mani.get('sha256', 'unknown')}`", ""] + [f"- {q}" if not q.startswith(("-", " ")) else q for q in Q] + \
        ["", "## Conversion", f"- Dates written: {sel[0][1]}..{sel[-1][1]} ({len(sel)} files) to `{paths.rel(out)}`; GeoTIFF float32, EPSG:4326, nodata {ND}, native 0.25 deg transform.",
         f"- NaN (missing/undefined) cell-days kept as nodata: {int(df['nan_cells'].sum())}; negative values: {neg}; > 1000 mm: {over} (flagged, not altered here; the workflow excludes them as invalid).",
         "- Read-back checks: " + "; ".join(rb[:6]), "", "## Day definition (provisional)", f"{imd.DAY_DEFINITION}.",
         "For a Sentinel-1 pass at ~06:01 IST on date D, the daily value labelled D (if it ends 08:30 IST on D) includes ~21.5 h BEFORE the pass and ~2.5 h after it; excluding it (as the workflow does) "
         "gives a completed-day antecedent estimate that ends 08:30 IST on D-1 and misses the last ~21.5 h before the pass. It is not an exact pre-pass 24-h total.",
         "", "Unresolved: day-label convention, grid-point registration (centre assumed), licence, and whether IMD's 'undefined' cells cover part of the Chennai coast."]
    (odir / "reports" / f"imd_inspection_{a.year}.md").write_text("\n".join(L), encoding="utf-8")
    status.record("IMD", status.PARTIAL, f"{len(sel)} daily native GeoTIFFs written ({sel[0][1]}..{sel[-1][1]}); day definition PROVISIONAL; run rainfall_workflow.py next.",
                  files=[paths.rel(out), paths.rel(base / "source.json"), f"outputs/reports/imd_inspection_{a.year}.md"], seconds=time.time() - t0)
    log.info("done: %s", f"outputs/reports/imd_inspection_{a.year}.md")


if __name__ == "__main__":
    main()
