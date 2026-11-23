#!/usr/bin/env python
"""Module S1W (V2.3) - scan Earth Engine COPERNICUS/S1_GRD for ALL Sentinel-1 acquisitions in a date window over the study area,
and compare each with the reference geometry (Sentinel-1A, DESCENDING, relative orbit 92 = the pinned Nov 2015 scenes).
Reads only metadata + a few small reduceRegion statistics (no downloads, no flood processing). Needs Earth Engine authentication.
Usage:  .\\.venv\\Scripts\\python scripts\\s1_window_scan.py --start 2015-11-20 --end 2015-12-21
Nothing is assumed to exist: only rows returned by Earth Engine are reported."""
import argparse
import sys
import time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial.study_area import load_study_area
from src.flood_detection import s1_params, s1_window


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-11-20")
    ap.add_argument("--end", default="2015-12-21", help="exclusive end date")
    ap.add_argument("--event", default="2015_nov", help="event whose pinned post scene defines the reference geometry")
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("S1W_scan"); paths.ensure_dirs()
    ev = next(e for e in s1_params.load_events()["events"] if e["id"] == a.event)
    ref_id = ev["scene_ids"]["post"][0]
    try:
        import ee
        from src.flood_detection import gee_sentinel1 as g1
        g1.init_ee(load_settings()["gee"].get("project") or None)
        wgs, _, aoi_meta = load_study_area()
        aoi = ee.Geometry(wgs.unary_union.__geo_interface__, proj="EPSG:4326", geodesic=False)
        aoi_area = aoi.area(1)

        def stats(img):
            vv = img.select("VV")
            valid = vv.mask().reduceRegion(ee.Reducer.mean(), aoi, 30, maxPixels=1e9).get("VV")
            ang = img.select("angle").reduceRegion(ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True), aoi, 100, maxPixels=1e9)
            cov = img.geometry().intersection(aoi, 1).area(1).divide(aoi_area).multiply(100)
            return ee.Feature(None, {
                "id": img.get("system:index"), "t": img.get("system:time_start"), "platform": img.get("platform_number"),
                "mode": img.get("instrumentMode"), "pols": img.get("transmitterReceiverPolarisation"),
                "rel_orbit": img.get("relativeOrbitNumber_start"), "abs_orbit": img.get("orbitNumber_start"),
                "pass": img.get("orbitProperties_pass"), "coverage_pct": cov,
                "valid_pct": ee.Number(valid).multiply(100), "angle_mean": ang.get("angle_mean"),
                "angle_min": ang.get("angle_min"), "angle_max": ang.get("angle_max")})

        col = ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(aoi)
        win = col.filterDate(a.start, a.end).filter(ee.Filter.eq("instrumentMode", "IW"))
        items = [f["properties"] for f in win.map(stats).getInfo()["features"]]
        refs = ee.ImageCollection([ee.Image(f"COPERNICUS/S1_GRD/{ref_id}")]).map(stats).getInfo()["features"]
        ref = refs[0]["properties"]
        all_iw = len(items)   # (V2.3) former separate size() query was unused; the window count is reported below
    except Exception as e:
        msg = f"Earth Engine NOT queried: {str(e)[:250]}"
        log.error(msg); status.record("S1W", status.BLOCKED, msg, requirements=["earthengine authenticate; set gee.project in config/settings.json"], seconds=time.time() - t0)
        return
    ref["platform"] = f"SENTINEL-1{str(ref['platform']).upper()[-1]}" if len(str(ref["platform"])) == 1 else ref["platform"]
    rows = []
    for it in items:
        it["platform"] = f"SENTINEL-1{str(it['platform']).upper()[-1]}" if len(str(it["platform"])) == 1 else it["platform"]
        v, why = s1_window.classify(it, ref)
        rows.append({**it, "date_utc": datetime.fromtimestamp(it["t"] / 1000, tz=timezone.utc).isoformat(timespec="seconds"),
                     "derived_rel_orbit": s1_window.derived_rel(it["id"]), "verdict": v, "reasons": "; ".join(why)})
    df = pd.DataFrame(rows).sort_values("date_utc") if rows else pd.DataFrame()
    out_csv = paths.OUT_TAB / f"s1_window_scan_{a.start}_{a.end}.csv"; df.to_csv(out_csv, index=False)
    grid_dates = s1_window.expected_cycle_dates("2015-11-12", a.start, (date.fromisoformat(a.end) - timedelta(days=1)).isoformat())
    found_dates = set(df["date_utc"].str[:10]) if len(df) else set()
    md = [f"# Sentinel-1 window scan {a.start} to {a.end} (exclusive)", "",
          f"Reference geometry (pinned post scene {ref_id}): platform {ref['platform']}, pass {ref['pass']}, relative orbit {ref['rel_orbit']}, mean incidence angle {ref['angle_mean']}.",
          f"Study-area polygon: kind={aoi_meta.get('kind')}, source={aoi_meta.get('source')}, area_km2={aoi_meta.get('area_km2')} (NOT verified as an official boundary unless stated).",
          f"Query: COPERNICUS/S1_GRD, filterBounds(AOI), IW only, ALL passes/relative orbits/platforms, dates {a.start} to {a.end} (end exclusive). Earth Engine returned {all_iw} IW items.",
          f"12-day repeat grid of the reference orbit in the window (planning aid, NOT availability): {', '.join(grid_dates)}",
          f"Grid dates actually present in Earth Engine: {', '.join(sorted(d for d in grid_dates if d in found_dates)) or 'none'}", "",
          "| id | date (UTC) | platform | pass | rel | cov % | valid % | angle mean | verdict | reasons |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['date_utc']} | {r['platform']} | {r['pass']} | {r['rel_orbit']} | {r['coverage_pct']:.1f} | {r['valid_pct']:.1f} | {r['angle_mean']:.2f} | {r['verdict']} | {r['reasons']} |"
                  if None not in (r['coverage_pct'], r['valid_pct'], r['angle_mean']) else f"| {r['id']} | {r['date_utc']} | {r['platform']} | {r['pass']} | {r['rel_orbit']} | n/a | n/a | n/a | {r['verdict']} | {r['reasons']} |")
    if not rows:
        md.append("| (no Sentinel-1 IW items returned) | | | | | | | | | |")
    rep = paths.OUT_REP / f"s1_window_scan_{a.start}_{a.end}.md"; rep.write_text("\n".join(md), encoding="utf-8")
    ok = [r for r in rows if r["verdict"] == "COMPATIBLE"]
    status.record("S1W", status.COMPLETED, f"{len(rows)} IW items in window; {len(ok)} compatible with ref geometry: {[r['date_utc'][:10] for r in ok]}",
                  files=[paths.rel(out_csv), paths.rel(rep)], seconds=time.time() - t0)
    log.info("\n".join(md))


if __name__ == "__main__":
    main()
