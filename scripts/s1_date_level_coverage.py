#!/usr/bin/env python
"""Module S1DC (V2.3, M4B) - date-level (multi-slice) Sentinel-1 coverage verification. READ-ONLY on the inventory outputs; writes SEPARATE files.
METADATA / lightweight only: no imagery is downloaded or preprocessed; no flood classification, flood extent, baseline or validation.

Step 1 (offline, always): from the inventory CSV (footprint column) + the local study-area polygon -> per date/pass/orbit/platform group:
  number of slices, combined footprint coverage, overlap, gap, time/pol/orbit compatibility. Overlap is counted ONCE (geometric union).
Step 2 (--ee, needs your authenticated Earth Engine): per group, slice metadata (CRS, nominal scale, cycle, slice numbers ...) and the pixel-level
  combined valid VV / VH share from a per-pixel image COUNT (valid in >=1 slice; overlap = valid in >=2). Data bands are never zero-filled; only the
  COUNT image is unmasked to 0 so that 'no slice has data here' is counted as not-covered instead of being dropped from the AOI mean.
Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\s1_date_level_coverage.py            # offline footprint/compatibility step
  .\\.venv\\Scripts\\python scripts\\s1_date_level_coverage.py --ee --overwrite
Options: --inventory-csv / --inventory-report (default: the 2021_nov inventory outputs), --must-include-date (default 2021-11-16), --overwrite."""
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
from src.flood_detection import s1_inventory as inv, s1_date_level as dl

STEM = "s1_2021_date_level_coverage"
INV_STEM = "s1_inventory_2021_nov_2021-09-01_2021-12-01"
SLICE_KEYS = {"cycle": "cycleNumber", "config_id": "instrumentConfigurationID", "resolution_m": "resolution_meters", "slice_number": "sliceNumber",
              "total_slices": "totalSlices", "abs_orbit_start": "orbitNumber_start", "abs_orbit_stop": "orbitNumber_stop",
              "rel_orbit_start": "relativeOrbitNumber_start", "rel_orbit_stop": "relativeOrbitNumber_stop", "product_type": "productType"}


def ee_check(group_rows, ids, ee, aoi, thr_log):
    """Lightweight Earth Engine verification of ONE group (small getInfo calls). Returns (slice_meta list, valid dict, overlap dict, n_found)."""
    d, ps, ro, pf = inv.group_key(group_rows[0])
    gc = ee.ImageCollection("COPERNICUS/S1_GRD").filter(ee.Filter.inList("system:index", ids))                      # exactly the inventory slices
    for k_, v_ in inv.group_query_props(d, ps, ro, pf).items():                                                      # + group key incl. platform_number
        gc = gc.filter(ee.Filter.eq(k_, v_))
    gc = gc.filter(ee.Filter.eq("instrumentMode", "IW"))

    def meta(img):
        props = {"id": img.get("system:index"), "t": img.get("system:time_start"), "bands": img.bandNames().join(","),
                 "crs": img.select(0).projection().crs(), "nominal_scale_m": img.select(0).projection().nominalScale()}
        props.update({k: img.get(v) for k, v in SLICE_KEYS.items()})
        return ee.Feature(None, props)
    slice_meta = [f["properties"] for f in gc.map(meta).getInfo()["features"]]
    valid, over = {}, {}
    for b in ("VV", "VH"):
        bc = gc.filter(ee.Filter.listContains("transmitterReceiverPolarisation", b))
        n = bc.size().getInfo()
        if n != len(ids):
            valid[b.lower()] = None; over[b.lower()] = None            # a slice lacks this band: no combined value is claimed
            continue
        cnt = bc.select(b).count().unmask(0)                           # per-pixel number of slices with data (a COUNT; SAR values are never filled)
        r = ee.Image.cat([cnt.gt(0).rename("u"), cnt.gt(1).rename("o")]).reduceRegion(ee.Reducer.mean(), aoi, 30, maxPixels=1e9).getInfo()
        valid[b.lower()] = None if r.get("u") is None else round(100.0 * r["u"], 3)
        over[b.lower()] = None if r.get("o") is None else round(100.0 * r["o"], 3)
    return slice_meta, valid, over, gc.size().getInfo()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory-csv", default=None); ap.add_argument("--inventory-report", default=None)
    ap.add_argument("--ee", action="store_true", help="add the lightweight Earth Engine slice-metadata / pixel-validity check")
    ap.add_argument("--must-include-date", action="append", default=None); ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--min-footprint", type=float, default=dl.THRESHOLDS["min_footprint_pct"]); ap.add_argument("--min-valid", type=float, default=dl.THRESHOLDS["min_valid_pct"])
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("S1DC"); paths.ensure_dirs()
    must = a.must_include_date or ["2021-11-16"]; thr = {"min_footprint_pct": a.min_footprint, "min_valid_pct": a.min_valid}
    icsv = Path(a.inventory_csv) if a.inventory_csv else paths.OUT_TAB / f"{INV_STEM}.csv"
    irep = Path(a.inventory_report) if a.inventory_report else paths.OUT_REP / f"{INV_STEM}.md"
    out_csv, out_slices, out_md = paths.OUT_TAB / f"{STEM}.csv", paths.OUT_TAB / f"{STEM}_slices.csv", paths.OUT_REP / f"{STEM}.md"
    if not a.overwrite and any(o.exists() for o in (out_csv, out_slices, out_md)):
        print("STOP: output exists, not overwritten (use --overwrite):", [str(o) for o in (out_csv, out_slices, out_md) if o.exists()]); return
    if not icsv.exists():
        msg = f"inventory CSV not found: {icsv}"; log.error(msg); status.record("S1DC", status.BLOCKED, msg, seconds=time.time() - t0); print(msg); return
    df = pd.read_csv(icsv)                                                      # READ ONLY: the inventory files are never modified
    if "footprint" not in df.columns:
        msg = "inventory CSV has no `footprint` column (re-run the inventory of M4-A or later)"; log.error(msg); status.record("S1DC", status.BLOCKED, msg, seconds=time.time() - t0); print(msg); return
    rows = df.where(pd.notnull(df), None).to_dict("records")
    groups = dl.groups_from_rows(rows)
    wgs, _, aoi_meta = load_study_area(); aoi_geom = wgs.unary_union
    fp_now, qcfg = inv.query_fingerprint(aoi_geom)
    fp_inv = dl.parse_inventory_fingerprint(irep.read_text(encoding="utf-8")) if irep.exists() else None
    fp_note = ("MATCH" if fp_inv and fp_now.startswith(fp_inv) else f"MISMATCH (inventory {fp_inv} vs current {fp_now[:12]}) - the AOI/query used for the inventory differs from the current one" if fp_inv
               else "inventory report not found: AOI consistency NOT verified")
    log.info("%d groups; AOI fingerprint %s; inventory fingerprint check: %s", len(groups), fp_now[:12], fp_note)
    ee = aoi = None
    if a.ee:
        try:
            import ee as _ee
            from src.flood_detection import gee_sentinel1 as g1
            ee = _ee; g1.init_ee(load_settings()["gee"].get("project") or None)
            aoi = ee.Geometry(aoi_geom.__geo_interface__, proj="EPSG:4326", geodesic=False)
        except Exception as e:
            msg = f"Earth Engine step NOT completed: {str(e)[:250]}"; log.error(msg); status.record("S1DC", status.BLOCKED, msg, seconds=time.time() - t0); print(msg); return
    out, slice_out = [], []
    for (d, ps, ro, pf), rs in groups.items():
        ids = [r["id"] for r in rs]
        fm = dl.footprint_metrics(aoi_geom, [dl.footprint_geom(r.get("footprint")) for r in rs])
        meta = None; valid = {"vv": None, "vh": None}; over = {"vv": None, "vh": None}; n_found = None; err = ""
        if a.ee:
            try:
                meta, valid, over, n_found = ee_check(rs, ids, ee, aoi, thr)
            except Exception as e:                                           # one failing group never aborts the others; the failure is recorded
                err = f"EE check failed: {str(e)[:200]}"; log.warning("%s %s", d, err)
        comp = dl.compat_checks(rs, meta)
        verdict, why = dl.assess_date(len(rs), fm, valid, comp, thr)
        if err: why = why + [err]
        if n_found is not None and n_found != len(ids): why = why + [f"Earth Engine returned {n_found} slices, inventory has {len(ids)}"]
        cc = None
        if fm:
            diffs = [abs(x - r["coverage_pct"]) for x, r in zip(fm["slice_coverage_pct"], rs) if r.get("coverage_pct") is not None]
            cc = round(max(diffs), 3) if diffs else None
        out.append({"date_utc": d, "pass": ps, "rel_orbit": ro, "platform": pf, "n_slices": len(rs), "slice_ids": ";".join(ids),
                    "slice_coverage_pct_inventory": ";".join(str(r.get("coverage_pct")) for r in rs),
                    "slice_coverage_pct_local": ";".join(map(str, fm["slice_coverage_pct"])) if fm else "",
                    "footprint_cross_check_max_diff_pp": cc,
                    "combined_footprint_coverage_pct": fm["combined_footprint_pct"] if fm else None,
                    "sum_of_slice_coverages_pct": fm["sum_of_slices_pct"] if fm else None,
                    "overlap_pct_of_aoi": fm["overlap_pct_of_aoi"] if fm else None, "overlap_km2": fm["overlap_km2"] if fm else None,
                    "gap_pct_of_aoi": fm["gap_pct_of_aoi"] if fm else None, "gap_km2": fm["gap_km2"] if fm else None,
                    "combined_valid_VV_pct": valid.get("vv"), "combined_valid_VH_pct": valid.get("vh"),
                    "pixel_overlap_VV_pct": over.get("vv"), "pixel_overlap_VH_pct": over.get("vh"), "earth_engine_checked": bool(a.ee and not err),
                    "covers_complete_aoi": verdict.startswith("COMPLETE"), "assessment": verdict, "reasons": "; ".join(why),
                    **{f"check_{k}": v for k, v in comp.items()}, "aoi_fingerprint": fp_now[:12], "aoi_area_km2": fm["aoi_km2"] if fm else None})
        for i, r in enumerate(rs):
            m = (meta or [{}] * len(rs))
            mm = next((x for x in (meta or []) if x.get("id") == r["id"]), {})
            slice_out.append({"date_utc": d, "slice_id": r["id"], "t_utc": r.get("date_utc"), "coverage_pct_inventory": r.get("coverage_pct"),
                              "valid_VV_pct_inventory": r.get("valid_pct"), "valid_VH_pct_inventory": r.get("valid_vh_pct"), **{k: mm.get(k) for k in ["crs", "nominal_scale_m", "bands", *SLICE_KEYS]}})
    res = pd.DataFrame(out); res.to_csv(out_csv, index=False); pd.DataFrame(slice_out).to_csv(out_slices, index=False)
    explicit = [dl.explicit_date_status(groups, m) for m in must]
    fmt = lambda v: "n/a" if v is None or (isinstance(v, float) and v != v) else v                                      # noqa: E731
    L = ["# Sentinel-1 2021 date-level (multi-slice) coverage verification", "",
         "METADATA / lightweight only. No flood classification, no flood extent, no baseline designation, no validation. The individual scene records in the inventory are unchanged; this is a separate summary.", "",
         f"- Input inventory (read only): `{paths.rel(icsv) if icsv.is_absolute() else icsv}`; groups = (UTC date, pass, relative orbit, platform): {len(groups)} group(s), {len(rows)} slice(s).",
         f"- AOI: {aoi_meta.get('kind')} (provisional, not the official GCC boundary), area from footprints' CRS EPSG:32644 = {res['aoi_area_km2'].dropna().iloc[0] if res['aoi_area_km2'].notna().any() else 'n/a'} km2. AOI/query fingerprint `{fp_now[:12]}`; inventory fingerprint check: **{fp_note}**.",
         f"- Thresholds (documented defaults, adjustable): combined footprint >= {thr['min_footprint_pct']} %, combined valid VV and VH >= {thr['min_valid_pct']} %.",
         f"- Earth Engine pixel/slice-metadata check: **{'RUN (this run)' if a.ee else 'NOT RUN - valid VV/VH shares are n/a; run with --ee on the authenticated machine'}**. Query settings: {qcfg}.",
         "- Overlap is counted once: combined footprint = geometric union; combined valid share = pixels with data in >= 1 slice (image count > 0). Data bands are not zero-filled; only the per-pixel COUNT is unmasked so no-data pixels are counted as not covered.",
         "- `valid` is the pixel-level (30 m sampling) measure; `footprint` is the product outline. Footprints are rounded to 5 decimal degrees in the inventory (~1 m).", "",
         "## Explicit date checks", ""]
    for e in explicit:
        if not e["present"]:
            L.append(f"- **{e['date']}: NOT IN THE INVENTORY** - nothing is inferred or invented for this date.")
        else:
            for k in e["groups"]:
                row = res[(res.date_utc == k[0]) & (res["pass"] == k[1]) & (res.rel_orbit == k[2]) & (res.platform == k[3])].iloc[0]
                L.append(f"- **{e['date']}** ({k[3]} {k[1]} rel orbit {k[2]}): {row.n_slices} slice(s); combined footprint {fmt(row.combined_footprint_coverage_pct)} %; gap {fmt(row.gap_pct_of_aoi)} % ({fmt(row.gap_km2)} km2); overlap {fmt(row.overlap_pct_of_aoi)} %; "
                         f"valid VV {fmt(row.combined_valid_VV_pct)} %, VH {fmt(row.combined_valid_VH_pct)} % -> **{row.assessment}**.")
    L += ["", "## Per-date results", "",
          "| date (UTC) | pass | rel orbit | platform | slices | slice cov % (inventory) | combined footprint % | overlap % | gap % | valid VV % | valid VH % | complete AOI | assessment |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res.itertuples():
        L.append(f"| {r.date_utc} | {r._2} | {r.rel_orbit} | {r.platform} | {r.n_slices} | {r.slice_coverage_pct_inventory} | {fmt(r.combined_footprint_coverage_pct)} | {fmt(r.overlap_pct_of_aoi)} | {fmt(r.gap_pct_of_aoi)} | {fmt(r.combined_valid_VV_pct)} | {fmt(r.combined_valid_VH_pct)} | {'yes' if r.covers_complete_aoi else 'NO'} | {r.assessment} |")
    L += ["", "## Compatibility checks (True / False / None = not assessable from the data at hand)", "",
          "| date | same group key | same pols | VV all | VH all | max slice time gap s | times compatible | same abs orbit | same CRS | same scale | same cycle | slice numbers consecutive | footprint cross-check pp |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res.itertuples():
        L.append(f"| {r.date_utc} | {r.check_same_group_key} | {r.check_same_pols} | {r.check_all_have_VV} | {r.check_all_have_VH} | {fmt(r.check_max_slice_time_gap_s)} | {r.check_acquisition_times_compatible} | {r.check_same_abs_orbit} | {r.check_same_crs} | {r.check_same_nominal_scale} | {r.check_same_cycle} | {r.check_slice_numbers_consecutive} | {fmt(r.footprint_cross_check_max_diff_pp)} |")
    L += ["", "## Reasons recorded", ""] + [f"- {r.date_utc}: {r.reasons}" for r in res.itertuples() if r.reasons] + [
          "", "## Implementation note: is the existing mosaicking logic safe?", "",
          "- Grouping key: acquisition (UTC) date, pass direction, relative orbit and platform (platform filter `platform_number` added in the M4-A review). Sentinel-1A/1B or different orbits/passes are never merged.",
          "- `date_group_valid_pct` in the inventory is VV only, computed on a first-wins mosaic at 30 m. It is a screening number: no VH, no footprint union, gap or overlap, no compatibility checks. It is NOT sufficient to claim a complete AOI observation; this module adds those checks.",
          "- A mosaic's value in an overlap strip comes from the first image in collection order. That does not affect coverage counts, but any later value-level preprocessing must define an explicit overlap rule (it must not be left to collection order).",
          "- No result here is a flood, baseline or accuracy statement."]
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    n_ok = int(res.covers_complete_aoi.sum()); miss = [e["date"] for e in explicit if not e["present"]]
    state = status.COMPLETED if not miss and (a.ee and all(res.earth_engine_checked)) else status.PARTIAL
    status.record("S1DC", state, f"{len(res)} groups; {n_ok} verified complete; EE pixel check {'run' if a.ee else 'NOT run'}; explicit dates missing: {miss or 'none'}", files=[paths.rel(out_csv), paths.rel(out_slices), paths.rel(out_md)], seconds=time.time() - t0)
    print(f"{len(res)} groups; {n_ok} complete; EE check {'run' if a.ee else 'NOT run'}; report: {out_md}")


if __name__ == "__main__":
    main()
