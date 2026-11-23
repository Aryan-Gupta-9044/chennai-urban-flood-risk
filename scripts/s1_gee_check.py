#!/usr/bin/env python
"""Module S1G (V2.1) - are the catalogue scenes of an event really in Earth Engine COPERNICUS/S1_GRD?
Also reads Earth Engine's own `relativeOrbitNumber_start` so the derived relative orbit can be checked against it.
Needs one-time Earth Engine authentication. Availability is claimed ONLY for rows reported FOUND.
Usage:  .\\.venv\\Scripts\\python scripts\\s1_gee_check.py --event 2015_nov
NO flood detection is run here."""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial.study_area import bounds_wgs84
from src.flood_detection import s1_catalog as cat
from src.flood_detection.s1_orbits import resolve_orbits

AUTH_HELP = """Earth Engine is not usable yet. One-time setup on Windows (PowerShell, in the project folder):
  1. .\\.venv\\Scripts\\earthengine authenticate
     (alternative: .\\.venv\\Scripts\\python -c "import ee; ee.Authenticate()")
     -> a browser opens; sign in with the Google account registered for Earth Engine and paste the code back.
  2. Earth Engine needs a Google Cloud project registered for Earth Engine (noncommercial use is free):
     put its id in config\\settings.json  ->  "gee": {"project": "YOUR-PROJECT-ID"}
  3. Re-run:  .\\.venv\\Scripts\\python scripts\\s1_gee_check.py --event @EVENT@"""


def load_scenes(csv, min_cov):
    df = pd.read_csv(csv)
    rows = []
    for r in df.to_dict("records"):
        r = {k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()}
        if r.get("coverage_pct") is not None and float(r["coverage_pct"]) < min_cov:
            continue
        if r.get("abs_orbit") is None:   # CSV written by V2.0: recompute orbit fields from the scene name
            o = resolve_orbits({"granuleName": r.get("granule") or r.get("scene"), "platform": r.get("platform"),
                                "flightDirection": r.get("direction"), "pathNumber": r.get("rel_orbit")})
            r.update(abs_orbit=o["abs_orbit"], rel_orbit_catalogue=o["rel_orbit_catalogue"],
                     rel_orbit_derived=o["rel_orbit_derived"], rel_orbit=o["rel_orbit"], scene=o["clean_name"] or r["scene"])
        rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="2015_nov")
    ap.add_argument("--csv", default="")
    ap.add_argument("--min-coverage", type=float, default=95.0)
    a = ap.parse_args()
    t0 = time.time()
    log = get_logger("S1G_gee_check")
    paths.ensure_dirs()
    csv = Path(a.csv) if a.csv else paths.OUT_TAB / f"s1_scenes_{a.event}.csv"
    if not csv.exists():
        status.record("S1G", status.BLOCKED, f"{csv.name} not found - run scripts/s1_availability.py first.", seconds=time.time() - t0)
        return
    scenes = load_scenes(csv, a.min_coverage)
    out_csv = paths.OUT_TAB / f"s1_gee_availability_{a.event}.csv"
    report = paths.OUT_REP / f"s1_gee_availability_{a.event}.md"
    try:
        import ee
        from src.flood_detection import gee_sentinel1 as g1
        g1.init_ee(load_settings()["gee"].get("project") or None)
        w = bounds_wgs84()
        geom = ee.Geometry.Rectangle(list(w), proj="EPSG:4326", geodesic=False)
        d0 = min(s["date"] for s in scenes)
        d1 = (date.fromisoformat(max(s["date"] for s in scenes)) + timedelta(days=2)).isoformat()
        col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(geom).filterDate(d0, d1)
               .filter(ee.Filter.eq("instrumentMode", "IW")))
        feats = col.map(lambda im: ee.Feature(None, {
            "id": im.get("system:index"), "rel": im.get("relativeOrbitNumber_start"), "abs": im.get("orbitNumber_start"),
            "pass": im.get("orbitProperties_pass"), "plat": im.get("platform_number"),
            "pol": im.get("transmitterReceiverPolarisation"), "t": im.get("system:time_start")}))
        items = [f["properties"] for f in feats.getInfo()["features"]]
        log.info("Earth Engine returned %d IW items between %s and %s", len(items), d0, d1)
    except Exception as e:
        msg = f"Earth Engine NOT queried: {str(e)[:250]}"
        log.error(msg)
        help_txt = AUTH_HELP.replace("@EVENT@", a.event)
        log.error(help_txt)
        lines = [f"# Earth Engine scene availability - {a.event}", "", "**STATUS: NOT QUERIED. No availability is claimed.**", "",
                 f"Reason: `{str(e)[:250]}`", "", "```", help_txt, "```", "", "## Scenes waiting to be checked", "",
                 "| scene | date | abs orbit | catalogue rel | derived rel | Earth Engine |", "|---|---|---|---|---|---|"]
        for s in scenes:
            lines.append(f"| {s['scene']} | {s['date']} | {s.get('abs_orbit')} | {s.get('rel_orbit_catalogue')} | "
                         f"{s.get('rel_orbit_derived')} | NOT QUERIED |")
        report.write_text("\n".join(lines), encoding="utf-8")
        status.record("S1G", status.BLOCKED, msg, files=[paths.rel(report)], requirements=[help_txt], seconds=time.time() - t0)
        return
    rows = cat.match_scenes(scenes, items)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    pd.DataFrame(items).to_csv(paths.OUT_TAB / f"s1_gee_collection_{a.event}.csv", index=False)
    found = [r for r in rows if r["status"] == "FOUND"]
    g_rel = sorted({int(r["gee_rel_orbit"]) for r in found if r["gee_rel_orbit"] is not None})
    dm = [r["derived_matches_gee"] for r in found if r["derived_matches_gee"] is not None]
    lines = [f"# Earth Engine scene availability - {a.event}", "",
             f"Queried COPERNICUS/S1_GRD (IW) over the study-area bounding box; {len(items)} items in the date range.",
             f"**{len(found)} of {len(rows)} catalogue scenes FOUND in Earth Engine.**", "",
             f"Earth Engine relative orbit(s) of the found scenes: {g_rel or 'n/a'}",
             f"ESA-formula derived orbit agrees with Earth Engine: {sum(1 for x in dm if x)} of {len(dm)} comparable scenes", "",
             "| scene | date | status | match | EE id | EE rel | EE abs | EE pass | EE platform | derived=EE | catalogue=EE |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['scene']} | {r['date']} | {r['status']} | {r['match_method']} | {r['gee_id']} | {r['gee_rel_orbit']} | "
                     f"{r['gee_abs_orbit']} | {r['gee_pass']} | {r['gee_platform']} | {r['derived_matches_gee']} | {r['catalogue_matches_gee']} |")
    report.write_text("\n".join(lines), encoding="utf-8")
    state = status.COMPLETED if len(found) == len(rows) and rows else status.PARTIAL
    status.record("S1G", state, f"{len(found)}/{len(rows)} scenes found in Earth Engine; EE relative orbit(s): {g_rel or 'n/a'}; "
                  f"derived orbit agrees for {sum(1 for x in dm if x)}/{len(dm)}.",
                  files=[paths.rel(out_csv), paths.rel(report)], extra={"ee_rel_orbits": g_rel}, seconds=time.time() - t0)
    log.info("report: %s", paths.rel(report))


if __name__ == "__main__":
    main()
