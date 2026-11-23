#!/usr/bin/env python
"""Module CH3 (V2.3) - CHIRPS v3 DAILY_SAT COVERAGE PROBE. Probe only: no bulk acquisition.

Checks, on the real Earth Engine collection `UCSB-CHC/CHIRPS/V3/DAILY_SAT`:
  1. metadata: band, projection/native grid, nominal scale, image count and date continuity for the context window;
  2. NoData/mask handling on ACTUAL exported test images (native grid via crs + crs_transform + dimensions), exported as
     [precipitation with masked->-9999, valid-mask band] and checked for consistency (masked cells never become 0 mm);
  3. coverage over the ACTUAL study-area polygon (exact polygon-cell intersection, not the bounding box): AOI-area coverage and
     valid/missing cells per date, plus temporal completeness (% of dates meeting --min-coverage). The two measures are reported separately.
If coverage is below the threshold the verdict is STOP; the threshold is never lowered automatically.
STATUS: written to the public EE API; NOT executed in the build sandbox (no EE login) = UNTESTED live. Helpers are unit-tested on synthetic arrays.
Usage (PowerShell, project folder):
  .\\.venv\\Scripts\\python scripts\\probe_chirps_coverage.py"""
import argparse
import csv
import hashlib
import io
import json
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial import chirps, rainfall as R
from src.geospatial.study_area import load_study_area

BASE = paths.DATA_EXT / "rainfall" / "chirps_v3_daily"
PROBE = BASE / "probe"
TAG = "chirps_v3_sat"
AUTH_HELP = ("Earth Engine is not usable. One-time setup (PowerShell, project folder): .\\.venv\\Scripts\\python -m pip install earthengine-api ; "
             "earthengine authenticate ; put your Cloud project id in config\\settings.json -> gee.project (yours: sylvan-mode-481804-f7).")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ms_to_date(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def download_tif(url, dest):
    import requests
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    data = r.content
    if data[:2] == b"PK":                                   # some EE exports arrive zipped
        z = zipfile.ZipFile(io.BytesIO(data)); names = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
        if len(names) != 1: raise RuntimeError(f"zip holds {len(names)} tif files: {z.namelist()}")
        data = z.read(names[0])
    if data[:4] not in (b"II*\x00", b"MM\x00*"):
        raise RuntimeError(f"download is not a GeoTIFF (first bytes {data[:60]!r})")
    Path(dest).write_bytes(data)
    return r.status_code, r.headers.get("Content-Type", "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--event", default="2015_nov_dec")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--test-dates", default="", help="comma list inside the window; default: first, 2015-11-15, 2015-12-01, last")
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--project", default=None)
    ap.add_argument("--reuse-exports", action="store_true", help="re-use test GeoTIFFs already in probe/ (they are RE-VALIDATED in full; provenance recorded as reused) instead of downloading again")
    ap.add_argument("--reuse-server-cache", action="store_true", help="re-use the saved per-date server results (probe/server_per_date_cache.json) if its window/cell count match")
    ap.add_argument("--skip-all-dates", action="store_true", help="skip the server-side per-date coverage over the whole window (test images only)")
    a = ap.parse_args()
    t0 = time.time(); paths.ensure_dirs(); PROBE.mkdir(parents=True, exist_ok=True)
    log = get_logger("chirps_probe")
    ev = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"][a.event]
    start, end = a.start or ev["context_window"][0], a.end or ev["context_window"][1]
    expected = R.daterange(start, end)
    tests = [date.fromisoformat(x) for x in a.test_dates.split(",") if x.strip()] or sorted({expected[0], date(2015, 11, 15), date(2015, 12, 1), expected[-1]} & set(expected))
    bad = [d for d in tests if d not in set(expected)]
    if bad:
        status.record("CH3", status.BLOCKED, f"test date(s) outside the window: {bad}"); print("BLOCKED:", bad); return 2

    try:
        g, _, meta = load_study_area()
    except FileNotFoundError as e:
        status.record("CH3", status.BLOCKED, str(e)); print("BLOCKED:", e); return 2
    aoi_wgs = g.geometry.union_all() if hasattr(g.geometry, "union_all") else g.geometry.unary_union
    try:
        import ee
        from src.flood_detection import gee_sentinel1 as g1
        g1.init_ee(a.project or load_settings()["gee"].get("project") or None)
        col = ee.ImageCollection(chirps.DATASET_ID)
        end_excl = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        win = col.filterDate(start, end_excl)
        n = int(win.size().getInfo())
        times = win.aggregate_array("system:time_start").getInfo()
        ymd = list(zip(win.aggregate_array("year").getInfo(), win.aggregate_array("month").getInfo(), win.aggregate_array("day").getInfo()))
        first = ee.Image(win.sort("system:time_start").first())
        finfo = first.getInfo()
        pj = first.select(chirps.BAND).projection()
        proj = pj.getInfo(); nominal = float(pj.nominalScale().getInfo())
    except Exception as e:                                   # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        status.record("CH3", status.BLOCKED, msg[:300] + " | " + AUTH_HELP); print("BLOCKED (Earth Engine metadata step):", msg, "\n", AUTH_HELP); return 2

    # ---- 1. metadata / dates / grid
    stamps = [ms_to_date(t) for t in times]
    dates = [s.date() for s in stamps]
    non_midnight = [s.isoformat() for s in stamps if (s.hour, s.minute, s.second) != (0, 0, 0)]
    prop_dates = [date(int(y), int(m), int(d)) for y, m, d in ymd]
    prop_mismatch = [(x.isoformat(), y.isoformat()) for x, y in zip(sorted(dates), sorted(prop_dates)) if x != y]
    cont = chirps.continuity(dates, expected)
    crs, tr = chirps.grid_from_ee_projection(proj)
    bands = [b["id"] for b in finfo.get("bands", [])]
    band_meta = next((b for b in finfo.get("bands", []) if b["id"] == chirps.BAND), {})
    import geopandas as gpd
    aoi = gpd.GeoSeries([aoi_wgs], crs=4326).to_crs(crs).iloc[0]
    win_cells = chirps.snap_window(tr, aoi.bounds, pad_cells=1)
    wtr = chirps.window_transform(tr, win_cells); shape = (win_cells[3], win_cells[2])
    weights, touch = chirps.aoi_cell_weights(wtr, shape, aoi)
    wb = chirps.window_bounds(tr, win_cells)
    print(f"[grid] crs={crs} transform={list(tr)[:6]} nominalScale={nominal:.1f} m bands={bands} images in window={n} (expected {len(expected)})")
    print(f"[aoi ] polygon area share inside {shape[0]}x{shape[1]} window = {weights.sum():.4f}; cells touching polygon = {int(touch.sum())} (bbox cells would be {int(np.ceil((aoi.bounds[2]-aoi.bounds[0])/tr.a)+1)}x{int(np.ceil((aoi.bounds[3]-aoi.bounds[1])/abs(tr.e))+1)})")
    if abs(weights.sum() - 1.0) > 1e-6:
        status.record("CH3", status.BLOCKED, "internal check: AOI not inside the export window"); print("BLOCKED: AOI window check failed"); return 2

    # ---- 2. exported test images on the native grid
    cell_poly = lambda r, c: [wtr.c + c * wtr.a, wtr.f + (r + 1) * wtr.e, wtr.c + (c + 1) * wtr.a, wtr.f + r * wtr.e]
    rows, cols = np.where(touch)
    pts = ee.FeatureCollection([ee.Feature(chirps.ee_point(ee, wtr.c + (c + .5) * wtr.a, wtr.f + (r + .5) * wtr.e, crs), {"cid": int(r * shape[1] + c)}) for r, c in zip(rows, cols)])
    import rasterio
    manifest = {"dataset": chirps.DATASET_ID, "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": []}
    test_cov, test_rows, export_problems, tested, not_assessed, local_valid = {}, [], [], {}, [], {}
    for d in tests:
        one = win.filterDate(d.isoformat(), (d + timedelta(days=1)).isoformat())
        k = int(one.size().getInfo())
        if k != 1:
            export_problems.append(f"{d}: {k} images for this date (expected 1)"); not_assessed.append(d.isoformat()); continue
        img = ee.Image(one.first()); p0 = img.select(chirps.BAND)
        exp = ee.Image.cat([p0.toFloat().unmask(chirps.EXPORT_NODATA).rename("precipitation"), p0.mask().toFloat().rename("valid")])
        dest = PROBE / f"{TAG}_{d:%Y%m%d}_probe.tif"
        reused = bool(a.reuse_exports and dest.exists())
        try:
            req = chirps.download_params(crs, wtr, shape)      # crs + crs_transform + dimensions; NO region/scale (ee ignores region when crs_transform is given)
            req_record = chirps.sanitize_request(req)           # copied BEFORE the call: ee.Image.getDownloadURL mutates the dict it receives (adds an ee.Image under 'image')
            if reused:
                http = ctype = url = None
            else:
                url = exp.getDownloadURL(dict(req))            # a throw-away copy goes to Earth Engine
                http, ctype = download_tif(url, dest)
        except Exception as e:                               # noqa: BLE001
            export_problems.append(f"{d}: export failed {type(e).__name__}: {str(e)[:200]}"); not_assessed.append(d.isoformat()); continue
        with rasterio.open(dest) as ds:
            arr = ds.read(); dtf, dshape, dcrs = ds.transform, (ds.height, ds.width), ds.crs
            info = {"count": ds.count, "shape": [ds.height, ds.width], "dtype": ds.dtypes[0], "file_nodata_attr": ds.nodata, "crs": str(ds.crs), "res": list(ds.res),
                    "transform": list(ds.transform)[:6], "bounds": list(ds.bounds)}
        probs = []
        if info["count"] != 2: probs.append(f"{info['count']} bands (expected 2)")
        grid_probs = chirps.check_export_grid(dtf, dshape, dcrs, wtr, shape, tr, crs)
        probs += grid_probs
        if not probs:
            probs += chirps.check_export(arr[0], arr[1])
        # coverage is ONLY computed from a validated export; an invalid export is "not assessed", never 0 % and never a pass
        valid = (arr[1] == 1) if not probs else None
        cov = chirps.coverage(valid, weights) if not probs else None
        # independent server-side check: sampled values at cell centres (masked pixels are dropped by EE)
        srv_note = ""
        if not probs:
            try:
                samp = p0.sampleRegions(collection=pts, properties=["cid"], projection=ee.Projection(crs, list(tr)[:6]), geometries=False).getInfo()["features"]
                sv = {int(f["properties"]["cid"]): f["properties"].get(chirps.BAND) for f in samp}
                mism = [cid for cid, v in sv.items() if v is None or abs(v - arr[0].reshape(-1)[cid]) > 1e-3]
                absent_but_valid = [int(r * shape[1] + c) for r, c in zip(rows, cols) if arr[1][r, c] == 1 and int(r * shape[1] + c) not in sv]
                present_but_masked = [cid for cid in sv if arr[1].reshape(-1)[cid] != 1]
                srv_note = f"server sample: {len(sv)} unmasked of {len(rows)} AOI cells; value mismatches={len(mism)}; valid-in-tif-but-absent-server={len(absent_but_valid)}; unmasked-server-but-masked-in-tif={len(present_but_masked)}"
                if mism or absent_but_valid or present_but_masked: probs.append("server sample disagrees with exported file: " + srv_note)
            except Exception as e:                           # noqa: BLE001
                srv_note = f"server sample check failed: {type(e).__name__}: {str(e)[:120]}"
        export_problems += [f"{d}: {x}" for x in probs]
        manifest["files"].append(chirps.manifest_file_record(
            name=dest.name, date_iso=d.isoformat(), sha256=sha256(dest), nbytes=dest.stat().st_size,
            mtime_utc=datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            provenance=("REUSED from an earlier run's download (re-validated in full this run; not downloaded again)" if reused else "downloaded this run"),
            request_sanitized=None if reused else req_record,
            request_note=("request not captured: the earlier run crashed before writing its manifest; the intended request is shown for reference" if reused else "request as sent (whitelisted fields only)"),
            http_status=http, content_type=ctype, url_host=None if url is None else url.split("?")[0], info=info, problems=probs))
        if reused: manifest["files"][-1]["intended_request_params"] = req_record
        if probs:
            not_assessed.append(d.isoformat())
            print(f"[test] {d}: EXPORT INVALID - coverage NOT ASSESSED. problems={probs}")
            if grid_probs:
                print("[test] grid validation failed: stopping further exports (no bulk, no relaxed validation)."); break
            continue
        test_cov[d.isoformat()] = cov["aoi_area_coverage"]; local_valid[d.isoformat()] = cov["cells_valid"]
        vals = arr[0][(arr[1] == 1)]
        test_rows.append({"date": d.isoformat(), **cov, "valid_cells_zero_mm": int((vals == 0).sum()), "valid_min": float(vals.min()) if vals.size else None,
                          "valid_max": float(vals.max()) if vals.size else None, "sentinel_cells": int((arr[0] == chirps.EXPORT_NODATA).sum()), "note": srv_note})
        tested[d.isoformat()] = {"valid": valid, "arr": arr}
        print(f"[test] {d}: grid OK {info['shape']} res={info['res']}; AOI-area coverage {cov['aoi_area_coverage']:.1%}; AOI cells valid {cov['cells_valid']}/{cov['cells_touching_aoi']}; "
              f"file nodata attr={info['file_nodata_attr']}; mask/zero/server-sample checks passed")

    # ---- 3. server-side per-date coverage over the whole window (polygon-weighted) + valid cells per date
    per_date = {}
    srv_err = None
    cache_path = PROBE / "server_per_date_cache.json"
    cache_note = "computed this run"
    if a.reuse_server_cache and not a.skip_all_dates and cache_path.exists():
        try:
            cj = json.loads(cache_path.read_text(encoding="utf-8"))
            if cj.get("window") == [start, end] and cj.get("cells_touching_aoi") == int(touch.sum()) and cj.get("crs") == crs and len(cj.get("per_date", {})) == len(expected):
                per_date = cj["per_date"]; cache_note = f"REUSED from cache written {cj.get('computed_utc')} (not recomputed)"
                print("[all-dates] re-using saved server results:", cache_note)
            else:
                print("[all-dates] cache does not match this window/grid/AOI; recomputing")
        except Exception as e:                               # noqa: BLE001
            print(f"[all-dates] cache unreadable ({type(e).__name__}); recomputing")
    if not a.skip_all_dates and not per_date:
        try:
            shrink = tr.a * 0.01
            rects = [[wtr.c + c * wtr.a + shrink, wtr.f + (r + 1) * wtr.e + shrink, wtr.c + (c + 1) * wtr.a - shrink, wtr.f + r * wtr.e - shrink] for r, c in zip(rows, cols)]
            cells_geom = chirps.ee_multipolygon_from_rects(ee, rects, crs)
            from shapely.geometry import mapping
            nv = sum(len(r.coords) for pg in (aoi.geoms if hasattr(aoi, 'geoms') else [aoi]) for r in [pg.exterior, *pg.interiors]); print(f'[aoi ] polygon vertices sent to Earth Engine: {nv}')
            poly = chirps.ee_geometry_from_geojson(ee, mapping(aoi), crs)
            ct = list(tr)[:6]

            def per_img(im):
                im = ee.Image(im); p = im.select(chirps.BAND)
                vc = p.reduceRegion(ee.Reducer.count().unweighted(), cells_geom, crs=crs, crsTransform=ct, maxPixels=1e8)
                m = p.mask().unmask(0).toFloat().rename("m")          # 1 = CHIRPS value present, 0 = masked (explicit, regardless of how .mask() treats its own footprint)
                seen = m.reduceRegion(ee.Reducer.count().unweighted(), cells_geom, crs=crs, crsTransform=ct, maxPixels=1e8)
                vsum = m.reduceRegion(ee.Reducer.sum().unweighted(), cells_geom, crs=crs, crsTransform=ct, maxPixels=1e8)
                cv = m.reduceRegion(ee.Reducer.mean(), poly, crs=crs, crsTransform=ct, maxPixels=1e8)
                mm = p.reduceRegion(ee.Reducer.mean(), poly, crs=crs, crsTransform=ct, maxPixels=1e8)
                return ee.Feature(None, {"t": im.get("system:time_start"), "valid_cells": vc.get(chirps.BAND), "cells_seen": seen.get("m"), "valid_cells_mask": vsum.get("m"), "cov": cv.get("m"), "mean_mm": mm.get(chirps.BAND)})
            feats = ee.FeatureCollection(win.map(per_img)).getInfo()["features"]
            for f in feats:
                pr = f["properties"]; dd = ms_to_date(pr["t"]).date().isoformat()
                per_date[dd] = {"valid_cells": pr.get("valid_cells"), "cells_seen": pr.get("cells_seen"), "valid_cells_mask": pr.get("valid_cells_mask"), "cov": pr.get("cov"), "mean_mm": pr.get("mean_mm")}
        except Exception as e:                               # noqa: BLE001
            srv_err = f"{type(e).__name__}: {str(e)[:300]}"; print("[all-dates] server-side per-date coverage FAILED:", srv_err)
        if per_date:                                         # checkpoint immediately so a later output failure cannot lose the 153-date results
            try:
                cache_path.write_text(json.dumps(chirps.json_safe({"dataset": chirps.DATASET_ID, "window": [start, end], "crs": crs, "cells_touching_aoi": int(touch.sum()),
                                      "computed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "per_date": per_date}), indent=1), encoding="utf-8")
            except Exception as e:                           # noqa: BLE001
                print(f"[all-dates] WARNING: could not write server cache: {type(e).__name__}: {e}")

    ncell = int(touch.sum()); date_rows = []; server_problems = []
    cov_by_date = {}
    for d in expected:
        pr = per_date.get(d.isoformat())
        if pr is None:
            date_rows.append({"date": d.isoformat(), "in_collection": d in set(dates), "aoi_cells": ncell, "cells_seen_by_server_geometry": None, "valid_cells": None, "missing_cells": None, "aoi_area_coverage": None, "mean_mm_valid_cells": None, "meets_threshold": False, "row_check": "NO SERVER ROW"})
            continue
        vc = int(pr["valid_cells"] or 0); cv = float(pr["cov"]) if pr["cov"] is not None else None
        rp = chirps.server_row_problems(ncell, pr.get("cells_seen"), pr["valid_cells"] if pr["valid_cells"] is not None else 0, cv, weights[touch])
        if pr.get("valid_cells_mask") is not None and int(round(pr["valid_cells_mask"])) != vc: rp.append(f"valid-cell counts disagree (value band {vc} vs mask band {pr['valid_cells_mask']})")
        if rp: server_problems.append(f"{d.isoformat()}: " + "; ".join(rp))
        if cv is not None: cov_by_date[d.isoformat()] = cv
        date_rows.append({"date": d.isoformat(), "in_collection": True, "aoi_cells": ncell, "cells_seen_by_server_geometry": pr.get("cells_seen"), "valid_cells": vc, "missing_cells": ncell - vc,
                          "aoi_area_coverage": None if cv is None else round(cv, 4), "mean_mm_valid_cells": pr["mean_mm"], "meets_threshold": cv is not None and cv >= a.min_coverage, "row_check": "OK" if not rp else "; ".join(rp)})
    comp = chirps.temporal_completeness(cov_by_date, [d.isoformat() for d in expected], a.min_coverage) if per_date else None
    # server vs local cross-check on test dates
    xchk = {d: (cov_by_date.get(d), test_cov[d]) for d in test_cov if d in cov_by_date}
    for d in test_cov:                                       # server calculation must reproduce the exported-file numbers on every validated test date
        pr = per_date.get(d)
        server_problems += [f"{d}: {x}" for x in chirps.compare_server_local(None if pr is None else pr.get("cov"), None if pr is None else pr.get("valid_cells"), test_cov[d], local_valid[d])]
    if per_date and not test_cov:
        server_problems.append("no validated exported image to verify the server-side calculation against")
    cont_s = {k: ([x.isoformat() for x in v] if isinstance(v, list) else v) for k, v in cont.items()}
    cont_chk = {"missing": cont["missing"], "duplicated": cont["duplicated"], "unexpected": cont["unexpected"]}
    verdict, why = chirps.verdict(a.min_coverage, test_cov, comp, cont_chk, export_problems, server_problems[:6] + ([f'... and {len(server_problems) - 6} more'] if len(server_problems) > 6 else []))
    if srv_err and not a.skip_all_dates:
        verdict = "STOP"; why.append("server-side per-date coverage failed: " + srv_err)

    # ---- outputs
    output_errors = []
    def safe(label, fn):
        try: fn()
        except Exception as e:                               # noqa: BLE001
            output_errors.append(f"{label}: {type(e).__name__}: {str(e)[:200]}"); print(f"[output] FAILED {label}: {type(e).__name__}: {e}")
    dropped = []
    manifest["server_per_date_source"] = cache_note
    manifest["verdict_at_write"] = {"note": "see chirps_v3_sat_probe.json for the final verdict"}
    safe("probe_manifest.json", lambda: (PROBE / "probe_manifest.json").write_text(json.dumps(chirps.json_safe(manifest, "$", dropped), indent=2), encoding="utf-8"))
    if dropped: print("[output] manifest: non-JSON objects were DROPPED (types only recorded):", dropped)
    tab = paths.OUT_TAB / f"{TAG}_probe_dates.csv"
    def w_dates():
        with open(tab, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(date_rows[0].keys())); w.writeheader(); w.writerows(chirps.json_safe(date_rows))
    safe("dates csv", w_dates)
    tab2 = paths.OUT_TAB / f"{TAG}_probe_test_images.csv"
    def w_tests():
        with open(tab2, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(test_rows[0].keys())); w.writeheader(); w.writerows(chirps.json_safe(test_rows))
    if test_rows: safe("test images csv", w_tests)
    cells_tab = paths.OUT_TAB / f"{TAG}_probe_aoi_cells.csv"
    first_t = next(iter(tested.values()), None)
    def w_cells():
        with open(cells_tab, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["row", "col", "centre_x", "centre_y", "aoi_area_share"] + [f"valid_{d}" for d in tested]);
            for r, c in zip(rows, cols):
                w.writerow([int(r), int(c), wtr.c + (c + .5) * wtr.a, wtr.f + (r + .5) * wtr.e, round(float(weights[r, c]), 5)] + [int(tested[d]["valid"][r, c]) for d in tested])
    safe("aoi cells csv", w_cells)
    fig_path = paths.OUT_FIG / f"{TAG}_probe_cells.png"
    def w_fig():
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        fig, ax = plt.subplots(figsize=(6, 7))
        for r in range(shape[0]):
            for c in range(shape[1]):
                x0 = wtr.c + c * wtr.a; y0 = wtr.f + (r + 1) * wtr.e
                col_ = "#cccccc" if not touch[r, c] else ("#4daf4a" if first_t["valid"][r, c] else "#e41a1c")
                ax.add_patch(Rectangle((x0, y0), wtr.a, -wtr.e, fc=col_, ec="white", alpha=0.7))
        gpd.GeoSeries([aoi], crs=crs).boundary.plot(ax=ax, color="k", lw=1.2)
        ax.set_xlim(wb[0], wb[2]); ax.set_ylim(wb[1], wb[3]); ax.set_aspect("equal")
        ax.set_title(f"CHIRPS v3 SAT native cells ({crs}) vs study-area polygon\ngreen=valid red=masked grey=outside AOI; test date {next(iter(tested))}", fontsize=9)
        fig.savefig(fig_path, dpi=150, bbox_inches="tight"); plt.close(fig)
    if first_t is not None: safe("cells figure", w_fig)
    if output_errors:
        verdict = "STOP"; why.append("an output file could not be written: " + "; ".join(output_errors))
    lic = chirps.LICENCE_NOTE
    L = [f"# CHIRPS v3 DAILY_SAT coverage probe ({TAG})", "",
         f"**Verdict: {verdict}**" + ("" if verdict == "STOP" else " (the user still has to review this before the bulk download is built)"), ""]
    if why: L += ["Reasons:"] + [f"- {x}" for x in why] + ["", "The threshold was NOT lowered automatically.", ""]
    L += ["## Status", "- Earth Engine calls: executed by this run on your machine (the build sandbox could not run them). Helper logic is unit-tested on synthetic arrays only.",
          "- Not validated. Not a flood-prediction result. SAT is IMERG-split but CHIRPS blends station data, so it is not independent of gauges.", "",
          "## Collection and grid", f"- Dataset `{chirps.DATASET_ID}`; bands {bands}; band `{chirps.BAND}` metadata: {json.dumps(band_meta)[:300]}",
          f"- Native projection reported by Earth Engine: crs `{crs}`, transform `{list(tr)[:6]}`, nominal scale {nominal:.1f} m. Native pixel size used for every export; no reproject, no resample.",
          f"- Images in window {start}..{end}: {n}; dates found {cont['found']} / expected {cont['expected']}; missing {len(cont['missing'])}; duplicated {len(cont['duplicated'])}; unexpected {len(cont['unexpected'])}",
          f"- Timestamps not at 00:00:00 UTC: {len(non_midnight)} {non_midnight[:3]}; year/month/day property mismatches: {len(prop_mismatch)} {prop_mismatch[:3]}",
          f"- Units: catalog says {chirps.UNITS_EXPECTED} (not independently checkable from pixel values).", "",
          "## Study-area coverage (actual polygon, exact cell intersection)",
          f"- Polygon cells touching the AOI: {ncell} (native cells, window {shape[0]}x{shape[1]} incl. 1-cell pad). The polygon lies fully inside the window (share {weights.sum():.4f}).",
          f"- Measure 1 - AOI area coverage: share of the polygon's area covered by valid CHIRPS pixels (threshold {a.min_coverage:.0%}).",
          f"- Measure 2 - Daily temporal completeness: % of the {len(expected)} dates meeting that threshold" + (f": **{comp['percent']:.1f}% ({comp['dates_meeting']}/{comp['dates_expected']}) - " + ("UNVERIFIED, NOT A COVERAGE RESULT (see reasons)" if (export_problems or server_problems) else "server-side, verified against the exported test images") + "**" if comp else ": NOT COMPUTED (server-side pass skipped/failed)") + ".", ""]
    if not_assessed: L += [f"Test dates NOT ASSESSED (export invalid or missing; no coverage figure is given for them, 0 % would be misleading): {not_assessed}", ""]
    if server_problems: L += ["Server-side verification problems:"] + [f"- {x}" for x in server_problems[:20]] + [""]
    L += ["### Export request used (native-grid window)", f"- `crs`={crs}, `crs_transform`={list(wtr)[:6]}, `dimensions`=[{shape[1]}, {shape[0]}] (width, height); no `region`, no `scale`. Expected window bounds {list(wb)}.",
          "- Earth Engine implements this as a re-grid onto the SAME 0.05 degree lattice (offset by whole cells); values are checked against native cell-centre samples, not assumed identical.", ""]
    L += ["### Exported test images (actual files in data/external/rainfall/chirps_v3_daily/probe/)", "| date | AOI area coverage | valid cells | missing cells | zero-mm valid cells | sentinel cells |", "|---|---|---|---|---|---|"]
    for r in test_rows: L.append(f"| {r['date']} | {r['aoi_area_coverage']:.1%} | {r['cells_valid']}/{r['cells_touching_aoi']} | {r['cells_missing']} | {r['valid_cells_zero_mm']} | {r['sentinel_cells']} |")
    L += ["", "NoData handling: masked pixels were exported as -9999 together with an explicit 0/1 valid band; consistency check = valid band is 0/1, every masked cell holds -9999, no valid cell holds -9999, "
          "no NaN, no negative rainfall, plus a server-side sample at cell centres. Genuine 0 mm in valid cells is counted separately and kept as 0.", ""]
    if xchk: L += ["Server (EE weighted-mean mask) vs local exact-geometry coverage on test dates: " + "; ".join(f"{d}: {s if s is None else round(s, 4)} vs {l:.4f}" for d, (s, l) in xchk.items()), ""]
    if per_date:
        miss_days = [r["date"] for r in date_rows if not r["meets_threshold"]]
        L += [f"Per-date table (valid/missing cells for every date): `outputs/tables/{TAG}_probe_dates.csv`. Dates below threshold: {len(miss_days)} {miss_days[:10]}", ""]
    L += ["## Caveats (recorded, not resolved)", f"- Day definition: {chirps.DAY_DEFINITION}", f"- Licence: {lic}",
          "- References: " + "; ".join(f"{k}: {v}" for k, v in chirps.REFERENCES.items()),
          "- DAILY_RNL (ERA5-split) was NOT examined or used; its catalog metadata must be verified separately before any later sensitivity run. SAT and RNL are never combined.",
          "- Outputs are kept apart from IMD (data/external/rainfall/chirps_v3_daily/ vs imd_gridded_daily/).", ""]
    L += ["## Provenance of this run", f"- Test rasters: " + ("; ".join(f"{m['date']}: {m['provenance']}" for m in manifest["files"]) or "none"),
          f"- Per-date server results: {cache_note}", f"- Output-writing failures: {output_errors or 'none'}", ""]
    rep = paths.OUT_REP / f"{TAG}_probe.md"; rep.write_text("\n".join(L), encoding="utf-8")
    (paths.OUT_REP / f"{TAG}_probe.json").write_text(json.dumps(chirps.json_safe({"verdict": verdict, "reasons": why, "min_coverage": a.min_coverage, "crs": crs, "transform": list(tr)[:6],
        "window": {"start": start, "end": end, "n_dates": len(expected)}, "cells_touching_aoi": ncell, "test_coverage": test_cov, "test_dates_not_assessed": not_assessed, "server_problems": server_problems[:50], "temporal_completeness_verified": not (export_problems or server_problems), "temporal_completeness": comp, "continuity": cont_s, "export_problems": export_problems, "output_errors": output_errors, "per_date_source": cache_note}), indent=2), encoding="utf-8")
    state = status.PARTIAL if verdict != "STOP" else status.BLOCKED
    status.record("CH3", state, f"probe verdict {verdict}: " + ("; ".join(why)[:300] if why else "coverage + mask checks passed; awaiting user review before bulk download"),
                  files=[rep, tab, cells_tab], seconds=time.time() - t0)
    print(f"\n=== VERDICT: {verdict} ===")
    for x in why: print(" -", x)
    unver = bool(export_problems or server_problems)
    if comp: print(f"AOI cells touching polygon: {ncell}; server-side temporal completeness: {comp['percent']:.1f}% ({comp['dates_meeting']}/{comp['dates_expected']}) - " + ("UNVERIFIED: NOT a coverage result" if unver else "verified against exported test images"))
    if not_assessed: print("Test dates NOT ASSESSED:", not_assessed)
    print("Report:", rep); print("Please send back:", rep.name, ",", tab.name, ",", cells_tab.name, "and", f"{TAG}_probe.json")
    return 0 if verdict != "STOP" else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
