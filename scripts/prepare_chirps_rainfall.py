#!/usr/bin/env python
"""Module CH3P (V2.3) - turn the verified raw CHIRPS v3 DAILY_SAT two-band rasters into the single-band daily files + source.json that rainfall_workflow.py reads.

Reads data/external/rainfall/chirps_v3_daily/raw/ (never modified). For every date with manifest status OK AND a matching SHA-256:
  daily/YYYYMMDD.tif : float32, native grid window (same CRS and transform as the raw file - no resample, no reproject), nodata -9999,
                       masked cells -> -9999 (never 0), genuine 0 mm kept as 0.
Dates that are FAILED/missing/checksum-mismatched get NO file (the workflow then reports them MISSING). Every date is logged.
Then: python scripts/rainfall_workflow.py --source-id chirps_v3_daily --event 2015_nov_dec"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial import chirps, chirps_acquire as CA, rainfall as R, chirps_runpaths as RP

NODATA = -9999.0


class ConversionError(RuntimeError):
    """A raw file could not be converted to a verified workflow raster."""


def convert_one(raw, out, d, meta, low_coverage=False):
    """Write the workflow daily file from a raw two-band file. The raster is written to `<out>.part`, read back and verified with EXPLICIT checks, and only then
    renamed to `out` (atomic). On any failure the partial file is removed and ConversionError is raised - a half-written output can never be mistaken for a success."""
    out = Path(out); part = out.with_name(out.name + ".part")
    try:
        with rasterio.open(raw) as ds:
            arr = ds.read(); prof = ds.profile.copy(); tr, crs = ds.transform, ds.crs
        probs = chirps.check_export(arr[0], arr[1])
        if probs: raise ConversionError("raw file breaks the mask rules: " + "; ".join(probs))
        valid = arr[1] == 1
        band = np.where(valid, arr[0], NODATA).astype("float32")
        prof.update(count=1, dtype="float32", nodata=NODATA, compress="deflate", driver="GTiff")
        prof.pop("photometric", None)
        with rasterio.open(part, "w", **prof) as dst:
            dst.write(band, 1)
            dst.set_band_description(1, f"CHIRPS v3 DAILY_SAT precipitation mm/d, label date {d.isoformat()} (day definition NOT verified)")
            tags = dict(source="UCSB-CHC/CHIRPS/V3/DAILY_SAT", date=d.isoformat(), units="mm/d", native_grid_window="true", resampled="false",
                        masked_cells="-9999 (never zero)", day_definition="PROVISIONAL / NOT VERIFIED", raw_sha256=meta["sha256"], doi=CA.DOI, licence="CC BY 4.0 (conservative)")
            if low_coverage: tags["coverage_status"] = "LOW_COVERAGE (below the acquisition threshold; included only because --include-low-coverage was set)"
            dst.update_tags(**tags)
        with rasterio.open(part) as chk:                     # explicit read-back verification (no assert statements: they vanish under python -O)
            if chk.crs != crs: raise ConversionError(f"read-back CRS {chk.crs} != raw CRS {crs}")
            if chk.transform != tr: raise ConversionError(f"read-back transform {chk.transform} != raw transform {tr}")
            b2 = chk.read(1)
            if b2.shape != band.shape: raise ConversionError(f"read-back shape {b2.shape} != {band.shape}")
            if chk.nodata != NODATA: raise ConversionError(f"read-back nodata {chk.nodata} != {NODATA}")
            if not np.array_equal(b2, band): raise ConversionError("read-back values differ from the converted array")
        os.replace(part, out)
    except Exception as e:                                   # noqa: BLE001
        for p_ in (part, out):
            try:
                if Path(p_).exists(): Path(p_).unlink()
            except OSError: pass
        if isinstance(e, ConversionError): raise
        raise ConversionError(f"{type(e).__name__}: {str(e)[:150]}") from e
    return {"cells": int(valid.size), "valid_cells": int(valid.sum()), "masked_cells": int((~valid).sum()), "zero_cells": int((band[valid] == 0).sum()),
            "min_mm": float(band[valid].min()) if valid.any() else None, "max_mm": float(band[valid].max()) if valid.any() else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--event", default="2015_nov_dec")
    ap.add_argument("--base-dir", default=None, help="CHIRPS data root of THIS run. Default: data/external/rainfall/chirps_v3_daily (the 2015 run)")
    ap.add_argument("--outputs-dir", default=None, help="outputs root of THIS run. Default: the project outputs/ (the 2015 run)")
    ap.add_argument("--status-id", default=None, help="status registry id (default CH3P = the 2015 entry; a non-2015 event must pass its own, e.g. CH3P_2021)")
    ap.add_argument("--include-low-coverage", action="store_true", help="ALSO convert dates acquired as LOW_COVERAGE (labelled in the file tags and the table); default: not converted")
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("chirps_prepare")
    try: rp = RP.resolve_run_paths("prepare", a.event, a.base_dir, a.outputs_dir, a.status_id)
    except RP.PathIsolationError as e: print("BLOCKED (path isolation):", e); return 2
    SID = rp["status_id"]; base = rp["base"]; raw = base / "raw"; daily = base / "daily"; od = rp["outputs"]
    for p in (od / "tables", od / "reports"): p.mkdir(parents=True, exist_ok=True)
    daily.mkdir(parents=True, exist_ok=True)
    for stale in daily.glob("*.part"): stale.unlink()        # leftovers of an interrupted conversion are never results
    ev = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"][a.event]
    expected = R.daterange(*ev["context_window"])
    m = CA.load_manifest(raw / "download_manifest.json")
    if m is None:
        status.record(SID, status.BLOCKED, f"no readable manifest at {raw / 'download_manifest.json'}; run scripts/fetch_chirps_rainfall.py first"); print("BLOCKED: no manifest"); return 2
    rows = []
    for d in expected:
        e = m["entries"].get(d.isoformat()); row = {"date": d.isoformat(), "status": "MISSING", "note": ""}
        f = raw / CA.raw_name(d)
        st = (e or {}).get("status")
        if e is None or st not in ("OK", "LOW_COVERAGE"):
            row["note"] = "not acquired (" + str((e or {}).get("last_error") or "no manifest entry") + ")"
        elif st == "LOW_COVERAGE" and not a.include_low_coverage:
            cvv = (e.get("validation") or {}).get("aoi_area_coverage")
            row["status"] = "LOW_COVERAGE_NOT_CONVERTED"; row["note"] = f"AOI-area coverage {cvv:.1%} below the acquisition threshold ({m.get('min_coverage')}); retained in raw/, not converted (use --include-low-coverage to override)" if cvv is not None else "LOW_COVERAGE; not converted"
        elif not f.exists():
            row["note"] = "manifest says OK but the raw file is absent"
        elif CA.sha256_file(f) != e.get("sha256"):
            row["status"] = "CHECKSUM_MISMATCH"; row["note"] = "raw file SHA-256 differs from the manifest: NOT converted"
        else:
            try:
                row.update(convert_one(f, daily / f"{d:%Y%m%d}.tif", d, e, low_coverage=(st == "LOW_COVERAGE"))); row["status"] = "CONVERTED" if st == "OK" else "CONVERTED_LOW_COVERAGE"
            except ConversionError as ex:
                row["status"] = "CONVERSION_FAILED"; row["note"] = str(ex)[:200]
        if not row["status"].startswith("CONVERTED"):
            stale = daily / f"{d:%Y%m%d}.tif"                  # an output from an earlier run must not survive for a date that is no longer acceptable
            if stale.exists(): stale.unlink(); row["note"] += " | stale daily file from an earlier run removed"
        rows.append(row); log.info("%s %s %s", row["date"], row["status"], row["note"])
    tab = od / "tables" / "chirps_v3_sat_conversion.csv"
    cols = ["date", "status", "cells", "valid_cells", "masked_cells", "zero_cells", "min_mm", "max_mm", "note"]
    with open(tab, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    nconv = sum(r["status"].startswith("CONVERTED") for r in rows); nlow = sum(r["status"] == "CONVERTED_LOW_COVERAGE" for r in rows)
    meta = {k: v for k, v in m.items() if k != "entries"}
    src = {"source_id": CA.SOURCE_ID if a.event == RP.DEFAULT_EVENT else base.name, "name": "CHIRPS v3 DAILY_SAT (UCSB-CHC/CHIRPS/V3/DAILY_SAT) via Google Earth Engine, native-grid window",
           "version": "CHIRPS v3.0 DAILY_SAT; manifest sha256 " + CA.sha256_file(raw / "download_manifest.json")[:12],
           "product_type": "satellite-blended (IMERG Late V07 disaggregation of station-adjusted pentads); not independent of gauges", "unit": "mm", "accumulation_hours": None,
           "low_coverage_dates_included": nlow, "day_definition": chirps.DAY_DEFINITION, "file_pattern": "daily/{date:%Y%m%d}.tif", "expected_crs": meta.get("crs", "EPSG:4326"), "nodata": NODATA,
           "native_resolution": "0.05 deg (native; Earth Engine grid 0.0500000007 deg); the files are a clipped window of the native grid, not resampled",
           "obtained_from": f"Google Earth Engine {chirps.DATASET_ID}; official archive {chirps.REFERENCES['chc_archive']}", "obtained_on": str(meta.get("retrieval_started_utc", ""))[:10],
           "licence_note": chirps.LICENCE_NOTE, "doi": CA.DOI, "attribution": CA.ATTRIBUTION, "validation_status": "NOT VALIDATED",
           "demo_status": "PROVISIONAL source for the V2.3 rainfall demo; event window PROVISIONAL; no anomaly (no >=10-year same-source baseline built)"}
    (base / "source.json").write_text(json.dumps(src, indent=2), encoding="utf-8")
    bad = [r for r in rows if not r["status"].startswith("CONVERTED")]
    L = ["# CHIRPS v3 DAILY_SAT - preparation for rainfall_workflow", "", f"- Converted {nconv} of {len(expected)} dates ({expected[0]}..{expected[-1]}); of these {nlow} are LOW_COVERAGE dates converted only because --include-low-coverage was set. Raw files untouched in `raw/`.",
         "- Daily files keep the raw CRS and transform exactly (native 0.05 deg window; no resample, no reproject). Masked cells = -9999; genuine 0 mm = 0.",
         f"- Not converted ({len(bad)}): " + (", ".join(f"{r['date']} [{r['status']}]" for r in bad[:15]) + (" ..." if len(bad) > 15 else "") if bad else "none"),
         f"- Day definition: {chirps.DAY_DEFINITION}", f"- {chirps.INDEPENDENCE_NOTE}", "", f"Next: `python scripts/rainfall_workflow.py --source-id {CA.SOURCE_ID if a.event == RP.DEFAULT_EVENT else base.name} --event {a.event}`", ""]
    rep = od / "reports" / "chirps_v3_sat_preparation.md"; rep.write_text("\n".join(L), encoding="utf-8")
    state = status.BLOCKED if not nconv else (status.COMPLETED if (nconv == len(expected) and nlow == 0) else status.PARTIAL)   # data completeness only; the provisional day definition is a caveat in the message/report, not a data gap
    status.record(SID, state, f"{nconv}/{len(expected)} dates converted; day definition provisional" + (f"; {len(bad)} missing" if bad else ""), files=[rep, tab], seconds=time.time() - t0)
    print(f"converted {nconv}/{len(expected)}; source.json written; report {rep}")
    return 0 if (nconv == len(expected) and nlow == 0) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
