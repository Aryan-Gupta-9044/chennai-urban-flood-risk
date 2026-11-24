#!/usr/bin/env python
"""Module S1I (V2.3) - Sentinel-1 acquisition inventory + candidate-baseline assessment (METADATA ONLY: no downloads, no flood processing).
Scans COPERNICUS/S1_GRD month by month (small getInfo() calls, cached per window so a failed run restarts where it stopped),
for ALL passes / relative orbits / platforms (IW, AOI intersection), and compares each item with the reference geometry.
Usage:  .\\.venv\\Scripts\\python scripts\\s1_inventory.py --start 2014-10-01 --end 2015-12-21
Options: --force (ignore cached windows)   Existing outputs of s1_window_scan.py are never touched (different file names).
         --event 2015_dec | 2021_nov  (windows from config/s1_inventory_events.json; outputs named s1_inventory_<event>_<start>_<end>.*, so earlier outputs are not overwritten)
         --overwrite (replace existing output files of the same name; without it the script stops instead of overwriting)."""
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
    ap.add_argument("--event", choices=["2015_dec", "2021_nov"], default=None)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    evcfg = None
    if a.event:
        evcfg = json.loads((paths.CONFIG / "s1_inventory_events.json").read_text(encoding="utf-8"))["events"][a.event]
        a.start, a.end = evcfg["start"], evcfg["end"]
    stem = f"s1_inventory_{a.event}_{a.start}_{a.end}" if a.event else f"s1_inventory_{a.start}_{a.end}"
    t0 = time.time(); log = get_logger("S1I_inventory"); paths.ensure_dirs()
    roles = json.loads((paths.CONFIG / "s1_candidate_roles.json").read_text(encoding="utf-8"))
    use_roles = evcfg is None or evcfg.get("uses_candidate_roles", False)
    ref = dict(roles["reference_geometry"]) if use_roles else None          # 2021: NO reference geometry is assumed
    outs = [paths.OUT_TAB / f"{stem}.csv", paths.OUT_TAB / f"{stem}_geometry_summary.csv", paths.OUT_REP / f"{stem}.md"]
    if not a.overwrite and any(o.exists() for o in outs):
        print("STOP: output exists, not overwritten (use --overwrite or a different --event/--start/--end):", [str(o) for o in outs if o.exists()]); return
    wins = inv.month_windows(a.start, a.end)
    log.info("%d monthly windows between %s and %s (end exclusive)", len(wins), a.start, a.end)
    try:
        import ee
        from src.flood_detection import gee_sentinel1 as g1
        g1.init_ee(load_settings()["gee"].get("project") or None)
        wgs, _, aoi_meta = load_study_area()
        aoi = ee.Geometry(wgs.unary_union.__geo_interface__, proj="EPSG:4326", geodesic=False)
        aoi_area = aoi.area(1)
        fp, qcfg = inv.query_fingerprint(wgs.unary_union)
        cache = paths.OUT_TAB / "s1_inventory_cache" / fp[:12]; cache.mkdir(parents=True, exist_ok=True)   # per AOI/query configuration; older caches are left untouched and ignored
        log.info("AOI/query fingerprint %s (cache dir %s)", fp[:12], paths.rel(cache))

        def stats(img):
            bn = img.bandNames()

            def band_valid_pct(b):   # share of AOI pixels (30 m) with data in band b; null when the scene has no such band (scene is KEPT)
                return ee.Algorithms.If(bn.contains(b), ee.Number(img.select(b).mask().reduceRegion(ee.Reducer.mean(), aoi, 30, maxPixels=1e9).get(b)).multiply(100), None)
            ang = ee.Algorithms.If(bn.contains("angle"), img.select("angle").reduceRegion(ee.Reducer.mean(), aoi, 100, maxPixels=1e9).get("angle"), None)
            cov = img.geometry().intersection(aoi, 1).area(1).divide(aoi_area).multiply(100)
            return ee.Feature(img.geometry(), {
                "id": img.get("system:index"), "t": img.get("system:time_start"), "platform": img.get("platform_number"),
                "mode": img.get("instrumentMode"), "pols": img.get("transmitterReceiverPolarisation"),
                "product": img.get("productType"), "resolution": img.get("resolution"),
                "rel_orbit": img.get("relativeOrbitNumber_start"), "abs_orbit": img.get("orbitNumber_start"),
                "pass": img.get("orbitProperties_pass"), "coverage_pct": cov,
                "bands": bn.join(","), "valid_vv_pct": band_valid_pct("VV"), "valid_vh_pct": band_valid_pct("VH"), "angle_mean": ang})

        col = ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(aoi).filter(ee.Filter.eq("instrumentMode", "IW"))
        items = []
        for w0, w1 in wins:
            cf = cache / f"{w0}_{w1}.json"; got = None; how = "queried"
            if cf.exists() and not a.force:
                got = inv.cache_load(cf, fp, (w0, w1)); how = "cached"           # None (re-query) unless fingerprint, window and schema match
            if got is None:
                for k in range(3):
                    try:
                        got = [dict(f["properties"], footprint=inv.round_geojson(f.get("geometry"))) for f in col.filterDate(w0, w1).map(stats).getInfo()["features"]]; break
                    except Exception as e:  # noqa
                        log.warning("window %s..%s attempt %d failed: %s", w0, w1, k + 1, str(e)[:160]); time.sleep(5 * (k + 1))
                if got is None:
                    raise RuntimeError(f"window {w0}..{w1} failed 3 times; re-run to resume (finished windows are cached)")
                inv.cache_save(cf, fp, qcfg, (w0, w1), got); how = "queried"
            log.info("window %s..%s: %d IW items (%s)", w0, w1, len(got), how)
            items += got
        items = [dict(i, platform=plat(i["platform"])) for i in inv.dedupe(items)]
        rows = []
        for it in items:
            it = dict(it, valid_pct=it.get("valid_vv_pct"))           # `valid_pct` = VV validity (None when the scene has no VV band); VH validity kept separately; set BEFORE classification
            v, why = s1_window.classify(it, ref) if ref else inv.assess_without_reference(it)
            utc, ist = inv.utc_ist(it["t"])
            rows.append({**it, "date_utc": utc, "date_ist": ist, **inv.pol_flags(it.get("pols")),
                         "derived_rel_orbit": s1_window.derived_rel(it["id"]), "verdict": v, "reasons": "; ".join(why)})
        rows.sort(key=lambda r: r["date_utc"])
        groups = inv.slice_groups(rows)
        for r in rows:   # date-level coverage for acquisitions split into several slices
            r["n_slices_same_date_orbit"] = len(groups.get(inv.group_key(r), [r["id"]]))
            r["date_group_valid_pct"] = None
        for (d, ps, ro, pf), ids in groups.items():
            d0 = d; d1 = (date.fromisoformat(d).toordinal() + 1)
            if not any(r.get("has_VV") for r in rows if inv.group_key(r) == (d, ps, ro, pf)):
                continue                                                          # no VV in this group: date-level VV validity stays None
            gc = col.filterDate(d0, date.fromordinal(d1).isoformat())
            for k_, v_ in inv.group_query_props(d, ps, ro, pf).items():           # includes platform_number: S1A and S1B are never mosaicked together
                gc = gc.filter(ee.Filter.eq(k_, v_))
            gc = gc.filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            vp = gc.select("VV").mosaic().mask().reduceRegion(ee.Reducer.mean(), aoi, 30, maxPixels=1e9).get("VV").getInfo()
            for r in rows:
                if inv.group_key(r) == (d, ps, ro, pf) and vp is not None:
                    r["date_group_valid_pct"] = round(float(vp) * 100, 2)
    except Exception as e:
        msg = f"Earth Engine inventory NOT completed: {str(e)[:250]}"
        log.error(msg); status.record("S1I", status.BLOCKED, msg, seconds=time.time() - t0); return

    df = pd.DataFrame(rows)
    out_csv = outs[0]; df.to_csv(out_csv, index=False)
    gsum = inv.geometry_summary(rows); gsum_csv = outs[1]; pd.DataFrame(gsum).to_csv(gsum_csv, index=False)
    cands = inv.candidate_table(roles["candidates"], rows, ref) if ref else []
    comp = inv.compatible_by_month(rows) if ref else {}
    n_comp = sum(len(v) for v in comp.values())
    n_incomplete = sum(1 for r in rows if (r.get("coverage_pct") is None or r["coverage_pct"] < 95.0 or r.get("valid_pct") is None or r["valid_pct"] < 90.0))
    L = [f"# Sentinel-1 acquisition inventory {a.start} to {a.end} (end exclusive)", "",
         "METADATA ONLY. No flood processing. Candidate roles are NOT confirmed hydrological labels.", "",
         f"- Query: COPERNICUS/S1_GRD, filterBounds(study-area polygon), IW only, ALL passes / relative orbits / platforms, {len(wins)} monthly windows (cached in `outputs/tables/s1_inventory_cache/`).",
         f"- AOI/query fingerprint (cache key): `{fp[:12]}`; query settings: {qcfg}. Cached windows are reused only when this matches.",
         f"- Scenes WITHOUT a VV band are kept (valid VV share = n/a) and counted in the polarisation totals; scenes without VH are kept too. `valid_vh_pct` is reported separately.",
         f"- Study-area polygon: kind={aoi_meta.get('kind')}, source={aoi_meta.get('source')}, area_km2={aoi_meta.get('area_km2')}. Provisional unless stated otherwise; not verified as the official GCC boundary.",
         (f"- Reference geometry: {ref['platform']} {ref['pass']} relative orbit {ref['rel_orbit']} (scene {ref['reference_scene']})." if ref else
          "- Reference geometry: NONE assumed for this event; scenes are grouped by (pass, relative orbit, platform) in the geometry summary. Previously inferred acquisition dates are not assumed correct."),
         f"- Items returned: {len(rows)} ({n_incomplete} with incomplete AOI coverage or valid share - RETAINED, flagged in `verdict`/`reasons`). " + (f"COMPATIBLE with the reference geometry: {n_comp}. " if ref else "") + f"Dual-pol VV+VH scenes: {sum(1 for r in rows if r['dual_pol_VV_VH'])}; VV only: {sum(1 for r in rows if r['has_VV'] and not r['has_VH'])}; NO VV: {sum(1 for r in rows if not r['has_VV'])}. Distinct (pass, rel. orbit, platform) geometries: "
         f"{sorted({(r['pass'], r['rel_orbit'], r['platform']) for r in rows})}.",
         f"- Valid % is the share of study-area pixels (30 m) with VV data; coverage % is footprint/AOI area; angle is the AOI mean incidence angle (100 m). "
         f"Acquisitions split into several slices on one date/orbit: {len(groups)} (see `date_group_valid_pct`).", "",
         "## Geometry summary (pass / relative orbit / platform)", "",
         "| pass | rel orbit | platform | scenes | dates | first | last | VV | VH | dual | incomplete AOI | mean cov % |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g_ in gsum:
        L.append(f"| {g_['pass']} | {g_['rel_orbit']} | {g_['platform']} | {g_['n_scenes']} | {g_['n_acquisition_dates']} | {g_['first_date']} | {g_['last_date']} | {g_['n_with_VV']} | {g_['n_with_VH']} | {g_['n_dual_pol']} | {g_['n_incomplete_aoi_coverage']} | {g_['mean_coverage_pct']} |")
    if evcfg and evcfg.get("claimed_dates"):
        L += ["", "## Third-party date claims (UNVERIFIED - compare with the inventory below)", ""]
        for cd in evcfg["claimed_dates"]:
            hit = [r for r in rows if r["date_utc"][:10] == cd["date"]]
            L.append(f"- {cd['date']}: {cd['claim']} -> " + (f"{len(hit)} IW item(s) in the collection that UTC date: " + "; ".join(f"{r['platform']} {r['pass']} rel {r['rel_orbit']}" for r in hit) if hit else "NO IW item in the collection on that UTC date"))
    if ref:
        L += ["", "## Candidate observations (Agent 1 roles)", "",
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
    else:
        L += ["", "## Candidate observations and baseline", "",
              "None configured for this event: no candidate dates, reference geometry or baseline are assumed. Choose them later from the geometry summary and this inventory, with rainfall context."]
    L += ["", "## Full inventory", "", "| id | date UTC | date IST | platform | pass | rel | abs | pols | cov % | valid % | VH valid % | slices | angle | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    fm = lambda x: "n/a" if x is None or x != x else f"{x:.1f}"
    for r in rows:
        L.append(f"| {r['id']} | {r['date_utc']} | {r['date_ist']} | {r['platform']} | {r['pass']} | {r['rel_orbit']} | {r['abs_orbit']} | {r['pols']} | "
                 f"{fm(r['coverage_pct'])} | {fm(r['valid_pct'])} | {fm(r.get('valid_vh_pct'))} | {r['n_slices_same_date_orbit']} | {fm(r['angle_mean'])} | {r['verdict']} |")
    rep = outs[2]; rep.write_text("\n".join(L), encoding="utf-8")
    status.record("S1I", status.COMPLETED, f"{len(rows)} IW items; {n_comp} compatible; candidates: " +
                  "; ".join(f"{c['date']}={c['result'].split(' in ')[0]}" for c in cands), files=[paths.rel(out_csv), paths.rel(gsum_csv), paths.rel(rep)], seconds=time.time() - t0)
    log.info("report: %s", paths.rel(rep))


if __name__ == "__main__":
    main()
