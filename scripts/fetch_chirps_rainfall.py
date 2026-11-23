#!/usr/bin/env python
"""Module CH3A (V2.3) - controlled acquisition of CHIRPS v3 DAILY_SAT (Earth Engine `UCSB-CHC/CHIRPS/V3/DAILY_SAT`) for the configured context window.

Only runs after the coverage probe PASSED (outputs/reports/chirps_v3_sat_probe.json: verdict PROCEED-TO-REVIEW) and re-uses its verified grid and AOI cells.
Each date is exported on the exact native 0.05 deg lattice (crs + crs_transform + dimensions) as the probe-verified two-band raster:
  band 1 precipitation (mm/d; masked -> -9999), band 2 valid (1 = CHIRPS value present, 0 = masked). Genuine 0 mm stays 0.
Resumable (re-run the same command), retried with backoff, every file re-validated (native grid, mask rules, server cell-centre sample), checksummed. Failed dates are
reported as MISSING - never replaced by zeros. Nothing is written into the IMD directory.
STATUS: Earth Engine part written to the public API and exercised only against an emulated ee in the build sandbox (UNTESTED live); the engine logic is unit-tested.
Usage (PowerShell, project folder):
  .\\.venv\\Scripts\\python scripts\\fetch_chirps_rainfall.py --project sylvan-mode-481804-f7            (add --limit 3 for a first smoke test)"""
import argparse
import csv
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import chirps, chirps_acquire as CA, rainfall as R
from src.geospatial.study_area import load_study_area

BASE = paths.DATA_EXT / "rainfall" / CA.SOURCE_ID
RAW = BASE / "raw"
MANIFEST = RAW / "download_manifest.json"
AUTH_HELP = ("Earth Engine is not usable. One-time setup: pip install earthengine-api ; earthengine authenticate ; "
             "put your Cloud project in config\\settings.json -> gee.project (yours: sylvan-mode-481804-f7) or pass --project.")


def probe_window(probe_json, dates_csv=None):
    """Exact (start, end, n_dates, source) the probe covered. Prefers `window` in the probe JSON (written by current probe versions); older probe results lack it, so
    fall back to the probe's per-date table (outputs/tables/chirps_v3_sat_probe_dates.csv): first/last date, count and contiguity. Returns (info, problems)."""
    j = json.loads(Path(probe_json).read_text(encoding="utf-8"))
    w = j.get("window")
    if isinstance(w, dict) and w.get("start") and w.get("end"):
        return {"start": w["start"], "end": w["end"], "n": w.get("n_dates"), "source": "probe JSON 'window'"}, []
    csv_path = Path(dates_csv) if dates_csv else Path(probe_json).resolve().parent.parent / "tables" / "chirps_v3_sat_probe_dates.csv"
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            ds = sorted(date.fromisoformat(r["date"]) for r in csv.DictReader(f))
    except Exception as e:                                   # noqa: BLE001
        return None, [f"probe window unknown: no 'window' in {probe_json} and the per-date table {csv_path} is unreadable ({type(e).__name__}); re-run the probe"]
    if not ds: return None, ["probe per-date table is empty"]
    if ds != R.daterange(ds[0].isoformat(), ds[-1].isoformat()): return None, ["probe per-date table is not a contiguous date range"]
    return {"start": ds[0].isoformat(), "end": ds[-1].isoformat(), "n": len(ds), "source": f"probe per-date table {csv_path.name}"}, []


def gate_on_probe(probe_json, crs, tr, ncell, start, end, dates_csv=None):
    """The bulk download is allowed only if the probe passed on THIS grid/AOI AND this exact start/end window. Returns list of problems."""
    p = []
    try:
        j = json.loads(Path(probe_json).read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        return [f"probe result not readable at {probe_json} ({type(e).__name__}); run scripts/probe_chirps_coverage.py first"]
    if j.get("verdict") != "PROCEED-TO-REVIEW": p.append(f"probe verdict is {j.get('verdict')!r}, not PROCEED-TO-REVIEW")
    if not j.get("temporal_completeness_verified"): p.append("probe temporal completeness was not verified")
    if j.get("crs") != crs: p.append(f"probe CRS {j.get('crs')} != current {crs}")
    pt = j.get("transform") or []
    if len(pt) != 6 or any(abs(a - b) > 1e-12 for a, b in zip(pt, list(tr)[:6])): p.append(f"probe grid transform {pt} != current native transform {list(tr)[:6]}")
    if j.get("cells_touching_aoi") != ncell: p.append(f"probe AOI cells {j.get('cells_touching_aoi')} != current {ncell} (study area changed?)")
    info, wp = probe_window(probe_json, dates_csv); p += wp
    if info is not None:
        if (info["start"], info["end"]) != (start, end):
            p.append(f"probe window {info['start']}..{info['end']} ({info['source']}) != requested {start}..{end}; re-run the probe for the requested window")
        n_req = len(R.daterange(start, end))
        if info.get("n") not in (None, n_req): p.append(f"probe window has {info.get('n')} dates, requested window has {n_req}")
    tc = j.get("temporal_completeness") or {}
    if not tc or tc.get("dates_meeting") != tc.get("dates_expected") or tc.get("dates_expected") != len(R.daterange(start, end)):
        p.append(f"probe temporal completeness {tc.get('dates_meeting')}/{tc.get('dates_expected')} does not cover every date of the requested window")
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--event", default="2015_nov_dec")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--project", default=None)
    ap.add_argument("--retries", type=int, default=4); ap.add_argument("--backoff", type=float, default=2.0)
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--force", action="store_true", help="re-download even if a valid file exists (old one is kept in raw/failed only if invalid)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N dates of the window (smoke test)")
    ap.add_argument("--probe-json", default=str(paths.OUT_REP / "chirps_v3_sat_probe.json"))
    a = ap.parse_args()
    t0 = time.time(); paths.ensure_dirs(); RAW.mkdir(parents=True, exist_ok=True); log = get_logger("chirps_fetch")
    ev = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"][a.event]
    start, end = a.start or ev["context_window"][0], a.end or ev["context_window"][1]
    expected = R.daterange(start, end)
    dates = expected[:a.limit] if a.limit else expected
    try:
        g, _, _ = load_study_area()
    except FileNotFoundError as e:
        status.record("CH3A", status.BLOCKED, str(e)); print("BLOCKED:", e); return 2
    aoi_wgs = g.geometry.union_all() if hasattr(g.geometry, "union_all") else g.geometry.unary_union
    try:
        import ee
        from src.flood_detection import gee_sentinel1 as g1
        g1.init_ee(a.project or load_settings()["gee"].get("project") or None)
        col = ee.ImageCollection(chirps.DATASET_ID)
        win = col.filterDate(start, (date.fromisoformat(end) + timedelta(days=1)).isoformat())
        n = int(win.size().getInfo())
        times = win.aggregate_array("system:time_start").getInfo()
        first = ee.Image(win.sort("system:time_start").first()); pj = first.select(chirps.BAND).projection(); proj = pj.getInfo()
    except Exception as e:                                   # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"; status.record("CH3A", status.BLOCKED, msg[:300] + " | " + AUTH_HELP); print("BLOCKED (Earth Engine metadata):", msg, "\n", AUTH_HELP); return 2
    from datetime import datetime, timezone
    found = [datetime.fromtimestamp(t / 1000, tz=timezone.utc).date() for t in times]
    cont = chirps.continuity(found, expected)
    if cont["missing"] or cont["duplicated"] or cont["unexpected"] or n != len(expected):
        msg = f"collection dates do not match the window: images={n} missing={cont['missing'][:5]} dup={cont['duplicated'][:5]} unexpected={cont['unexpected'][:5]}"
        status.record("CH3A", status.BLOCKED, msg); print("BLOCKED:", msg); return 2
    crs, tr = chirps.grid_from_ee_projection(proj)
    import geopandas as gpd
    aoi = gpd.GeoSeries([aoi_wgs], crs=4326).to_crs(crs).iloc[0]
    wcells = chirps.snap_window(tr, aoi.bounds, pad_cells=1); wtr = chirps.window_transform(tr, wcells); shape = (wcells[3], wcells[2])
    weights, touch = chirps.aoi_cell_weights(wtr, shape, aoi); ncell = int(touch.sum())
    problems = gate_on_probe(a.probe_json, crs, tr, ncell, start, end)
    if abs(weights.sum() - 1.0) > 1e-6: problems.append("AOI is not fully inside the export window")
    if problems:
        status.record("CH3A", status.BLOCKED, "probe gate failed: " + "; ".join(problems)[:400]); print("BLOCKED - probe gate failed:"); [print(" -", x) for x in problems]; return 2
    print(f"[gate] probe passed on this grid. window {start}..{end} = {len(expected)} dates (downloading {len(dates)}); native {crs} pixel {tr.a} deg; export window {shape[0]}x{shape[1]} cells; AOI cells {ncell}")

    rows, cols = np.where(touch)
    pts = ee.FeatureCollection([ee.Feature(chirps.ee_point(ee, wtr.c + (c + .5) * wtr.a, wtr.f + (r + .5) * wtr.e, crs), {"cid": int(r * shape[1] + c)}) for r, c in zip(rows, cols)])
    req0 = chirps.download_params(crs, wtr, shape)

    def export_fn(d, tmp):
        import requests
        one = win.filterDate(d.isoformat(), (d + timedelta(days=1)).isoformat())
        if int(one.size().getInfo()) != 1: raise RuntimeError(f"{d}: expected exactly 1 image")
        p0 = ee.Image(one.first()).select(chirps.BAND)
        exp = ee.Image.cat([p0.toFloat().unmask(chirps.EXPORT_NODATA).rename("precipitation"), p0.mask().toFloat().rename("valid")])
        rec = chirps.sanitize_request(req0)                  # copy taken BEFORE the call: ee mutates the dict it receives
        url = exp.getDownloadURL(dict(req0))
        r = requests.get(url, timeout=180); r.raise_for_status()
        Path(tmp).write_bytes(CA.tif_bytes_from_download(r.content))
        return {"http_status": r.status_code, "content_type": r.headers.get("Content-Type", ""), "request_params": rec, "url_host": url.split("?")[0]}

    def validator(d, path):
        res = CA.validate_raw(path, crs=crs, native_tr=tr, win_tr=wtr, shape=shape, weights=weights, touch=touch)
        if res["problems"]: return res
        import rasterio
        with rasterio.open(path) as ds: arr = ds.read()
        one = win.filterDate(d.isoformat(), (d + timedelta(days=1)).isoformat())
        p0 = ee.Image(one.first()).select(chirps.BAND)
        samp = p0.sampleRegions(collection=pts, properties=["cid"], projection=ee.Projection(crs, list(tr)[:6]), geometries=False).getInfo()["features"]
        sv = {int(f["properties"]["cid"]): f["properties"].get(chirps.BAND) for f in samp}
        flat_p, flat_v = arr[0].reshape(-1), arr[1].reshape(-1)
        mism = [cid for cid, v in sv.items() if v is None or abs(v - flat_p[cid]) > 1e-3]
        absent = [int(r * shape[1] + c) for r, c in zip(rows, cols) if arr[1][r, c] == 1 and int(r * shape[1] + c) not in sv]
        masked_but_present = [cid for cid in sv if flat_v[cid] != 1]
        if mism or absent or masked_but_present:
            res["problems"].append(f"server cell-centre sample disagrees with file (value mismatches {len(mism)}, valid-in-file-but-absent-server {len(absent)}, unmasked-server-but-masked-in-file {len(masked_but_present)})")
        else:
            res["server_sample_check"] = f"{len(sv)} unmasked of {len(rows)} AOI cells agree"
        return res

    header = {"dataset": chirps.DATASET_ID, "variant": "DAILY_SAT", "doi": CA.DOI, "attribution": CA.ATTRIBUTION, "licence_note": chirps.LICENCE_NOTE,
              "day_definition": chirps.DAY_DEFINITION, "window": [start, end], "crs": crs, "native_transform": list(tr)[:6], "export_window_transform": list(wtr)[:6],
              "export_window_shape_rows_cols": list(shape), "aoi_cells": ncell, "export_request": chirps.sanitize_request(req0),
              "units": "mm/d (per Earth Engine catalog; not independently checkable)", "references": chirps.REFERENCES,
              "retrieval_started_utc": CA.utcnow(), "band_convention": "band1 precipitation (masked -> -9999), band2 valid 0/1; genuine zero rainfall kept as 0",
              "independence_note": chirps.INDEPENDENCE_NOTE, "validation_status": "NOT VALIDATED"}
    m = CA.acquire(dates, RAW, export_fn, validator, MANIFEST, header=header, retries=a.retries, backoff=a.backoff, force=a.force, log=print, min_coverage=a.min_coverage)
    summ = CA.summarize(m, expected, a.min_coverage)             # judged over the WHOLE window, even when --limit restricted this run

    # ---- outputs: checksums, per-date integrity table, provenance, report
    sums = [f"{e['sha256']}  {e['file']}" for k, e in sorted(m["entries"].items()) if e.get("status") in ("OK", "LOW_COVERAGE")]       # checksums for every RETAINED valid file
    (RAW / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    (BASE / "source_metadata.json").write_text(json.dumps({k: v for k, v in m.items() if k != "entries"}, indent=1, default=str), encoding="utf-8")
    tab = paths.OUT_TAB / "chirps_v3_sat_acquisition.csv"
    with open(tab, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["date", "status", "attempts", "file", "bytes", "sha256", "http_status", "aoi_cells", "cells_valid", "cells_missing", "aoi_area_coverage", "zero_cells_valid", "sentinel_cells", "valid_min_mm", "valid_max_mm", "note"])
        for d in expected:
            e = m["entries"].get(d.isoformat())
            if e is None:
                w.writerow([d.isoformat(), "NOT ATTEMPTED"] + [""] * 13); continue
            v = e.get("validation") or {}
            w.writerow([d.isoformat(), e.get("status"), len(e.get("attempts", [])), e.get("file"), e.get("bytes"), e.get("sha256"), e.get("http_status"), v.get("cells_touching_aoi"), v.get("cells_valid"),
                        v.get("cells_missing"), None if "aoi_area_coverage" not in v else round(v["aoi_area_coverage"], 4), v.get("zero_cells_valid"), v.get("sentinel_cells"), v.get("valid_min"), v.get("valid_max"), e.get("last_error") or v.get("server_sample_check", "")])
    full = summ["complete"]                                 # every expected date passed integrity AND the coverage threshold
    L = ["# CHIRPS v3 DAILY_SAT acquisition report", "",
         f"**Result: {'COMPLETE' if full else 'INCOMPLETE'}** - {summ['ok']} of {len(expected)} dates in {start}..{end} accepted (integrity + >= {a.min_coverage:.0%} AOI-area coverage)" + (f" (this run attempted {len(dates)})" if len(dates) != len(expected) else "") + ".", ""]
    if summ["failed_or_missing"]: L += [f"MISSING / FAILED dates ({len(summ['failed_or_missing'])}), not filled with zeros: {summ['failed_or_missing']}", ""]
    if summ["low_coverage"]: L += [f"LOW_COVERAGE dates ({len(summ['low_coverage'])}): valid files with AOI-area coverage below {a.min_coverage:.0%}. They are RETAINED in raw/ (inspection, resumability) but NOT accepted, and block COMPLETE: {summ['low_coverage']}", ""]
    okcov = [e["validation"]["aoi_area_coverage"] for e in m["entries"].values() if e.get("status") == "OK"]
    L += ["## Integrity", f"- Dataset `{chirps.DATASET_ID}` (variant DAILY_SAT); DOI {CA.DOI}; retrieval started {header['retrieval_started_utc']} UTC.",
          f"- Grid: {crs}, native pixel {tr.a} deg (nominal 0.05; Earth Engine reports 0.0500000007), export window {shape[0]}x{shape[1]} native cells (a clipped window of the native grid, NOT a resample); AOI-intersecting cells {ncell}.",
          f"- Every accepted file passed: 2 bands, native CRS/pixel size/lattice alignment/window origin/shape, valid band 0/1, masked cells = -9999 only, no NaN, no negative rainfall, and a server cell-centre sample agreeing with the file.",
          f"- AOI-area coverage over accepted dates: min {min(okcov):.1%}, max {max(okcov):.1%}." if okcov else "- No accepted dates.",
          f"- Checksums: `data/external/rainfall/{CA.SOURCE_ID}/raw/SHA256SUMS.txt` and `download_manifest.json` (per-date attempts, HTTP status, sha256, request fields, validation). Per-date table: `outputs/tables/chirps_v3_sat_acquisition.csv`.", "",
          "## Limitations (unchanged by acquisition)", f"- Day definition: {chirps.DAY_DEFINITION}", f"- Licence: {chirps.LICENCE_NOTE}", f"- {chirps.INDEPENDENCE_NOTE}",
          f"- Native 0.05 deg (about 5.5 km): the AOI spans {ncell} cells; this adds no finer spatial information. No resampling was done.", "- Not validated; not a flood-prediction result. Event window remains PROVISIONAL.", ""]
    rep = paths.OUT_REP / "chirps_v3_sat_acquisition.md"; rep.write_text("\n".join(L), encoding="utf-8")
    state = status.COMPLETED if full else status.PARTIAL
    status.record("CH3A", state, f"{summ['ok']}/{len(expected)} dates accepted; missing/failed {len(summ['failed_or_missing'])}; LOW_COVERAGE {len(summ['low_coverage'])}; day definition provisional", files=[rep, tab, MANIFEST], seconds=time.time() - t0)
    print(f"\n=== ACQUISITION {'COMPLETE' if full else 'INCOMPLETE'}: {summ['ok']}/{len(expected)} dates accepted ===")
    if summ["low_coverage"]: print(f"LOW_COVERAGE (retained, not accepted; AOI-area coverage < {a.min_coverage:.0%}):", summ["low_coverage"])
    if summ["failed_or_missing"]: print("MISSING/FAILED:", summ["failed_or_missing"], "\nRe-run the same command to resume (verified files are kept).")
    print("Report:", rep); return 0 if full else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
