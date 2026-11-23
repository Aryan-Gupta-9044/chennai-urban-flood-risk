#!/usr/bin/env python
"""Module S1I (V2.3) - Sentinel-1 acquisition inventory + candidate-baseline assessment (METADATA ONLY: no downloads, no flood processing).
Scans COPERNICUS/S1_GRD month by month (small getInfo() calls, cached per window so a failed run restarts where it stopped),
for ALL passes / relative orbits / platforms (IW, AOI intersection), and compares each item with the reference geometry.
Usage:  .\\.venv\\Scripts\\python scripts\\s1_inventory.py --start 2014-10-01 --end 2015-12-21
Options: --force (ignore cached windows)   Existing outputs of s1_window_scan.py are never touched (different file names)."""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial.study_area import load_study_area
from src.flood_detection import s1_window, s1_inventory as inv

NOT_ASSESSED = "NOT ASSESSED (no rainfall/hydrological data obtained yet)"


def plat(v):
    v = str(v)
    return f"SENTINEL-1{v.upper()[-1]}" if len(v) == 1 else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2014-10-01")
    ap.add_argument("--end", default="2015-12-21", help="exclusive")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("S1I_inventory"); paths.ensure_dirs()
    roles = json.loads((paths.CONFIG / "s1_candidate_roles.json").read_text(encoding="utf-8"))
    ref = dict(roles["reference_geometry"])
    cache = paths.OUT_TAB / "s1_inventory_cache"; cache.mkdir(exist_ok=True)
    wins = inv.month_windows(a.start, a.end)
    log.info("%d monthly windows between %s and %s (end exclusive)", len(wins), a.start, a.end)
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
            ang = img.select("angle").reduceRegion(ee.Reducer.mean(), aoi, 100, maxPixels=1e9).get("angle")
            cov = img.geometry().intersection(aoi, 1).area(1).divide(aoi_area).multiply(100)
            return ee.Feature(None, {
                "id": img.get("system:index"), "t": img.get("system:time_start"), "platform": img.get("platform_number"),
                "mode": img.get("instrumentMode"), "pols": img.get("transmitterReceiverPolarisation"),
                "product": img.get("productType"), "resolution": img.get("resolution"),
                "rel_orbit": img.get("relativeOrbitNumber_start"), "abs_orbit": img.get("orbitNumber_start"),
                "pass": img.get("orbitProperties_pass"), "coverage_pct": cov,
                "valid_pct": ee.Number(valid).multiply(100), "angle_mean": ang})

        col = ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(aoi).filter(ee.Filter.eq("instrumentMode", "IW"))
        items = []
        for w0, w1 in wins:
            cf = cache / f"{w0}_{w1}.json"
            if cf.exists() and not a.force:
                got = json.loads(cf.read_text(encoding="utf-8")); how = "cached"
            else:
                got = None
                for k in range(3):
                    try:
                        got = [f["properties"] for f in col.filterDate(w0, w1).map(stats).getInfo()["features"]]; break
                    except Exception as e:  # noqa
                        log.warning("window %s..%s attempt %d failed: %s", w0, w1, k + 1, str(e)[:160]); time.sleep(5 * (k + 1))
                if got is None:
                    raise RuntimeError(f"window {w0}..{w1} failed 3 times; re-run to resume (finished windows are cached)")
                cf.write_text(json.dumps(got), encoding="utf-8"); how = "queried"
            log.info("window %s..%s: %d IW items (%s)", w0, w1, len(got), how)
            items += got
        items = [dict(i, platform=plat(i["platform"])) for i in inv.dedupe(items)]
        rows = []
        for it in items:
            v, why = s1_window.classify(it, ref)
            utc, ist = inv.utc_ist(it["t"])
            rows.append({**it, "date_utc": utc, "date_ist": ist, "has_VH": "VH" in str(it.get("pols")),
                         "derived_rel_orbit": s1_window.derived_rel(it["id"]), "verdict": v, "reasons": "; ".join(why)})
        rows.sort(key=lambda r: r["date_utc"])
        groups = inv.slice_groups(rows)
        for r in rows:   # date-level coverage for acquisitions split into several slices
            r["n_slices_same_date_orbit"] = len(groups.get(inv.group_key(r), [r["id"]]))
            r["date_group_valid_pct"] = None
        for (d, ps, ro, pf), ids in groups.items():
            d0 = d; d1 = (date.fromisoformat(d).toordinal() + 1)
            m = (col.filterDate(d0, date.fromordinal(d1).isoformat()).filter(ee.Filter.eq("orbitProperties_pass", ps))
                 .filter(ee.Filter.eq("relativeOrbitNumber_start", ro)).select("VV").mosaic())
            vp = float(m.mask().reduceRegion(ee.Reducer.mean(), aoi, 30, maxPixels=1e9).get("VV").getInfo()) * 100
            for r in rows:
                if inv.group_key(r) == (d, ps, ro, pf):
                    r["date_group_valid_pct"] = round(vp, 2)
    except Exception as e:
        msg = f"Earth Engine inventory NOT completed: {str(e)[:250]}"
        log.error(msg); status.record("S1I", status.BLOCKED, msg, seconds=time.time() - t0); return

    df = pd.DataFrame(rows)
    out_csv = paths.OUT_TAB / f"s1_inventory_{a.start}_{a.end}.csv"; df.to_csv(out_csv, index=False)
    cands = inv.candidate_table(roles["candidates"], rows, ref)
    comp = inv.compatible_by_month(rows)
    n_comp = sum(len(v) for v in comp.values())
    L = [f"# Sentinel-1 acquisition inventory {a.start} to {a.end} (end exclusive)", "",
         "METADATA ONLY. No flood processing. Candidate roles are NOT confirmed hydrological labels.", "",
         f"- Query: COPERNICUS/S1_GRD, filterBounds(study-area polygon), IW only, ALL passes / relative orbits / platforms, {len(wins)} monthly windows (cached in `outputs/tables/s1_inventory_cache/`).",
         f"- Study-area polygon: kind={aoi_meta.get('kind')}, source={aoi_meta.get('source')}, area_km2={aoi_meta.get('area_km2')}. Provisional unless stated otherwise; not verified as the official GCC boundary.",
         f"- Reference geometry: {ref['platform']} {ref['pass']} relative orbit {ref['rel_orbit']} (scene {ref['reference_scene']}).",
         f"- Items returned: {len(rows)}. COMPATIBLE with the reference geometry: {n_comp}. Distinct (pass, rel. orbit, platform) geometries: "
         f"{sorted({(r['pass'], r['rel_orbit'], r['platform']) for r in rows})}.",
         f"- Valid % is the share of study-area pixels (30 m) with VV data; coverage % is footprint/AOI area; angle is the AOI mean incidence angle (100 m). "
         f"Acquisitions split into several slices on one date/orbit: {len(groups)} (see `date_group_valid_pct`).", "",
         "## Candidate observations (Agent 1 roles)", "",
         "| date | candidate role | category | result in Earth Engine | image id(s) | images that date |", "|---|---|---|---|---|---|"]
    for c in cands:
        L.append(f"| {c['date']} | {c['role']} | {c['category']} | {c['result']} | {c['ids']} | {c['n_images_that_date']} |")
    L += ["", "## Same-geometry (COMPATIBLE) acquisitions by month", ""]
    L += [f"- {m}: {', '.join(d)}" for m, d in comp.items()] or ["- none"]
    L += ["", "## Baseline suitability (engineering evidence only)", "",
          f"Only {n_comp} compatible acquisitions exist in the queried archive, so a robust seasonal backscatter baseline is NOT available. "
          "Rainfall/flood history before each candidate has not been analysed here (no rainfall data obtained).", "",
          "| date | category | geometry/coverage check | days before 12 Nov | days before ~1 Dec peak | preceding rain / flood evidence | assessment |", "|---|---|---|---|---|---|---|"]
    for c in cands:
        d = date.fromisoformat(c["date"])
        res = c["result"]
        ass = ("DRY NOT ESTABLISHED" if c["category"] in ("dry-candidate", "sensitivity") else
               "FLOOD/WET OBSERVATION (role unconfirmed)" if c["category"] in ("known-flood", "post-peak") else "HYDROLOGICALLY UNCERTAIN")
        if "NOT FOUND" in res or "OTHER" in res:
            ass = "NOT USABLE (" + res + ")"
        L.append(f"| {c['date']} | {c['category']} | {res} | {(date(2015, 11, 12) - d).days} | {(date(2015, 12, 1) - d).days} | {NOT_ASSESSED} | {ass} |")
    L += ["", "## Full inventory", "", "| id | date UTC | date IST | platform | pass | rel | abs | pols | cov % | valid % | slices | angle | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    fm = lambda x: "n/a" if x is None or x != x else f"{x:.1f}"
    for r in rows:
        L.append(f"| {r['id']} | {r['date_utc']} | {r['date_ist']} | {r['platform']} | {r['pass']} | {r['rel_orbit']} | {r['abs_orbit']} | {r['pols']} | "
                 f"{fm(r['coverage_pct'])} | {fm(r['valid_pct'])} | {r['n_slices_same_date_orbit']} | {fm(r['angle_mean'])} | {r['verdict']} |")
    rep = paths.OUT_REP / f"s1_inventory_{a.start}_{a.end}.md"; rep.write_text("\n".join(L), encoding="utf-8")
    status.record("S1I", status.COMPLETED, f"{len(rows)} IW items; {n_comp} compatible; candidates: " +
                  "; ".join(f"{c['date']}={c['result'].split(' in ')[0]}" for c in cands), files=[paths.rel(out_csv), paths.rel(rep)], seconds=time.time() - t0)
    log.info("report: %s", paths.rel(rep))


if __name__ == "__main__":
    main()
