#!/usr/bin/env python
"""DEP-2: independent flood-reference evidence, reference integration, exposure and vulnerability (Chennai).

Usage (PowerShell, repository root):
  .\\.venv\\Scripts\\python.exe scripts\\dep2_run.py all
  .\\.venv\\Scripts\\python.exe scripts\\dep2_run.py <stage> [--config config\\dep2.json]
Stages: acquire, evidence, reference, exposure, vulnerability, integrate, maps, contract, manifest, all

Writes only inside the configured output directory (versioned, new). Accepted SUS-1 / S1WC / rainfall
outputs are listed as protected and are never written. Sources are fetched from pinned commits and
verified by SHA-256 before use.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from dep2 import cdmp, exposure, layers, maps, reference, vulnerability  # noqa: E402
from dep2.common import (ANALYSIS_CRS, GEO_CRS, LOG, VERSION, environment, guard_output_dir, manifest, read_json,  # noqa: E402
                         setup_logging, sha256_file, utcnow, write_csv, write_gpkg, write_json)

STAGES = ["acquire", "evidence", "reference", "exposure", "vulnerability", "integrate", "maps", "contract", "manifest"]
OPTIONAL = ["sus1overlay"]  # needs outputs/susceptibility_v1 rasters (owner machine); not part of "all" when they are absent


class Ctx:
    def __init__(self, cfg_path: Path):
        self.cfg_path = cfg_path
        self.cfg = read_json(cfg_path)
        rp = lambda p: Path(p) if Path(p).is_absolute() else ROOT / p  # noqa: E731
        self.rp = rp
        self.out = rp(self.cfg["output_dir"])
        self.raw = rp(self.cfg["raw_dir"])
        self.src = layers.Sources(self.raw)
        guard_output_dir(self.out, [rp(p) for p in self.cfg["protected_outputs"]])
        self.A, self.B, self.C, self.D, self.E, self.F, self.G = (self.out / s for s in (
            "A_evidence_reference", "B_exposure", "C_vulnerability", "D_integration", "E_documentation", "F_maps", "G_ml_dashboard"))
        self.int = self.out / "_intermediate"
        for d in (self.A, self.B, self.C, self.D, self.E, self.F, self.G, self.int):
            d.mkdir(parents=True, exist_ok=True)
        self._wards = None

    @property
    def wards(self):
        if self._wards is None:
            self._wards = layers.load_wards(self.src)
        return self._wards


# ------------------------------------------------------------------------------------------------ stages
def st_acquire(c: Ctx):
    from dep2.acquire import acquire
    cache = [Path(x) for x in c.cfg.get("acquire_cache_dirs", [])]
    log = acquire(c.rp(c.cfg["sources_manifest"]), c.raw, cache_dirs=cache)
    write_json(c.A / "source_sha256_acquisition_log.json", log)


def st_evidence(c: Ctx):
    reg = pd.DataFrame(read_json(c.rp(c.cfg["evidence_register"]))["entries"])
    write_csv(reg, c.A / "evidence_register.csv")
    md = ["# Evidence register (DEP-2)", "", "Classes: E1 independent spatial flood reference; E2 independent georeferenced observation; E3 reported/administrative; "
          "E4 satellite-derived candidate; E5 contextual. Nothing is upgraded because it is useful.", "",
          "| ID | Source | Event | Observation | Class | Acquisition | Independence | Key limitation |", "|---|---|---|---|---|---|---|---|"]
    for _, r in reg.iterrows():
        md.append(f"| {r.evidence_id} | {r.source_name} | {r.event} | {r.observation_date} | **{r.evidence_class}** | {r.acquisition_status} | {r.independence} | {r.limitations} |")
    md += ["", "Full fields (publisher, publication date, time zone, accuracy, coverage, format, URL, licence, verification, intended use): `evidence_register.csv`."]
    (c.A / "evidence_register.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    ch = read_json(c.rp(c.cfg["event_chronology"]))
    write_csv(pd.DataFrame(ch["rows"]), c.A / "event_chronology.csv")
    write_csv(pd.DataFrame(ch["s1_date_assessment_2021"]), c.A / "s1_2021_date_reassessment.csv")
    md = ["# Event chronology (IST)", "", "Event time and reporting time are kept apart; 'unknown' means the source gives no time. Sentinel-1 times are from the project's inventory tables.", "",
          "| Event | Date (IST) | Time (IST) | What | Kind | Source |", "|---|---|---|---|---|---|"]
    md += [f"| {r['event']} | {r['date_ist']} | {r['time_ist']} | {r['what']} | {r['kind']} | {r['source']} |" for r in ch["rows"]]
    md += ["", "## Reassessment of the eight 2021 Sentinel-1 dates", "", "| S1 date | Status before DEP-2 | DEP-2 reassessment | Evidence |", "|---|---|---|---|"]
    md += [f"| {r['s1_date']} | {r['preliminary_status_before_dep2']} | {r['dep2_reassessment']} | {r['evidence_ids']} |" for r in ch["s1_date_assessment_2021"]]
    (c.A / "event_chronology.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    # CDMP records: verify depth classes against the PDF, place them, keep unplaced
    hist = pd.read_csv(c.src.history)
    ver, rec = cdmp.verify_depth_classes(hist, c.src.cdmp_pdf)
    write_csv(rec.assign(pdf_counts=rec.pdf_counts.astype(str), extracted_counts=rec.extracted_counts.astype(str)), c.A / "cdmp_depth_class_page_reconciliation.csv")
    xt = pd.crosstab(ver.depth_class_extracted.fillna("missing"), ver.depth_class_verified.fillna("UNVERIFIED")).reset_index()
    write_csv(xt, c.A / "cdmp_depth_class_extracted_vs_verified.csv")
    loc = cdmp.locate_records(ver, c.src.flood_spots)
    loc = loc.sjoin(c.wards[["ward_no", "geometry"]], how="left", predicate="intersects").drop(columns="index_right")
    loc = loc[~loc.index.duplicated(keep="first")]
    loc["ward_matches_geometry"] = np.where(loc.placed, pd.to_numeric(loc.ward, errors="coerce") == loc.ward_no, pd.NA)
    loc = loc.drop(columns="ward_no")
    wi = c.wards.set_index("ward_no").geometry
    pw = pd.to_numeric(loc.ward, errors="coerce")
    loc["distance_to_printed_ward_m"] = [wi[int(x)].distance(g) if (pl and x == x and int(x) in wi.index) else np.nan for x, g, pl in zip(pw, loc.geometry, loc.placed)]
    dd = loc.loc[loc.placed, "distance_to_printed_ward_m"]
    write_json(c.A / "cdmp_placement_qa.json", {"placed": int(loc.placed.sum()), "inside_printed_ward_share": float((dd == 0).mean()),
                                                "within_250m_of_printed_ward_share": float((dd <= 250).mean()), "max_distance_m": float(dd.max()),
                                                "note": "the gazetteer searches each name inside its own ward plus 250 m, so distances <= ~250 m are by design"})
    loc.to_pickle(c.int / "cdmp_located.pkl")
    write_csv(loc.drop(columns="geometry"), c.A / "cdmp_inundation_records_all_years.csv")
    for yr in (2015, 2021):
        g = loc[(loc.year == yr) & loc.placed].copy()
        write_gpkg(g, c.A / f"cdmp_inundation_locations_{yr}.gpkg", f"cdmp_{yr}")
    # edition cross-check (2015 in the 2024 vs 2026 CDMP)
    h24 = pd.read_csv(c.src.history_2024)
    e = pd.DataFrame({"year": [2015], "records_2026_edition": [int((hist.year == 2015).sum())], "records_2024_edition": [int((h24.year == 2015).sum())],
                      "wards_2026_edition": [int(hist[hist.year == 2015].ward.nunique())], "wards_2024_edition": [int(h24[h24.year == 2015].ward.nunique())]})
    write_csv(e, c.A / "cdmp_edition_crosscheck_2015.csv")
    summ = loc.groupby("year").agg(records=("row_id", "size"), placed=("placed", "sum"), wards=("ward", "nunique"),
                                   depth_verified=("depth_verification", lambda s: int((s == "VERIFIED_AGAINST_PDF").sum()))).reset_index()
    summ["placed_share"] = summ.placed / summ.records
    write_csv(summ, c.A / "cdmp_records_summary_by_year.csv")
    # 2015 crowd-sourced streets (originals kept; analysis copy in EPSG:32644)
    import geopandas as gpd
    for tag, p in (("dec2", c.src.osmin_dec2), ("dec31", c.src.osmin_dec31)):
        g = gpd.read_file(p)
        g = g.set_crs(GEO_CRS) if g.crs is None else g
        g = g.to_crs(ANALYSIS_CRS)
        g["is_flooded_raw"] = g.is_flooded.astype(str)
        g = g.drop(columns=[x for x in ("is_flooded",) if x in g])
        g["osm_id"] = g.osm_id.astype(str)
        g["dup_osm_id"] = g.osm_id.duplicated(keep="first")
        cg = g.geometry.representative_point().to_crs(GEO_CRS)
        g["outside_chennai_region"] = ~(cg.x.between(79.9, 80.5) & cg.y.between(12.6, 13.5)).values  # e.g. Bengaluru, Puducherry, Tokyo test edits
        g["evidence_class"] = "E3"
        g["observation_type"] = "REPORTED (anonymous crowd-sourced street flag)"
        write_gpkg(g, c.A / f"osmin_flooded_streets_2015_{tag}.gpkg", f"osmin_{tag}")
    LOG.info("evidence stage done")


def _harness_aoi(c: Ctx, root: Path):
    """Write a SUBSTITUTE AOI (union of the 200 TNGIS GCC wards) into a HARNESS copy only."""
    import geopandas as gpd
    assert (root / "src/flood_detection/ref_integration.py").is_file()
    marker = root / "DEP2_HARNESS_NOT_A_PROJECT_REPOSITORY.txt"
    if not marker.is_file():
        raise SystemExit("STOP: substitute AOI may be written only into a harness copy containing DEP2_HARNESS_NOT_A_PROJECT_REPOSITORY.txt")
    u = gpd.GeoDataFrame({"name": ["SUBSTITUTE AOI: union of 200 TNGIS GCC wards (not the project AOI)"]}, geometry=[c.wards.union_all()], crs=ANALYSIS_CRS)
    (root / "data/processed").mkdir(parents=True, exist_ok=True)
    u.to_crs(GEO_CRS).to_file(root / "data/processed/study_area_wgs84.geojson", driver="GeoJSON")
    u.to_file(root / "data/processed/study_area_utm44n.geojson", driver="GeoJSON")
    write_json(root / "data/processed/study_area_meta.json", {"source": "DEP-2 harness substitute (TNGIS GCC wards union)", "is_project_aoi": False})


def st_reference(c: Ctx):
    import geopandas as gpd
    loc = pd.read_pickle(c.int / "cdmp_located.pkl")
    loc = gpd.GeoDataFrame(loc, geometry="geometry", crs=ANALYSIS_CRS)
    refdir = c.A / "reference_inputs"
    refdir.mkdir(exist_ok=True)
    acq = read_json(c.raw / "ACQUISITION_LOG.json")
    obtained = acq["verified_utc"][:10]
    refs = []
    for yr in (2021, 2015):
        pts = reference.reference_points(loc, yr)
        f = refdir / f"REF-{yr}-CDMP_points.geojson"
        if f.exists():
            f.unlink()
        pts.to_file(f, driver="GeoJSON")
        meta = reference.checker_sidecar(
            f"REF-{yr}-CDMP", f"GCC CDMP 2026 inundated locations, monsoon {yr} (placed records, representative points)", "Greater Chennai Corporation (table); placement by reclaimchennai gazetteer",
            f"GCC City Disaster Management Plan 2026, 'Depth of Inundation During Monsoon - {yr}'; PDF sha256 {sha256_file(c.src.cdmp_pdf)}; extraction+placement github.com/reclaimchennai/chennai-monsoon-map@56c3a6a",
            obtained, "Government publication, licence not stated (derived statistics used internally; PDF not redistributed)", False, "points", f"{yr}-01-01", f"{yr}-12-31", True, True,
            None, {"1": f"location listed by GCC as inundated during the {yr} monsoon (presence only)", "0": "NOT DEFINED - absence of a listing is not absence of flooding"},
            "Administrative list (street/locality names) placed by gazetteer within its ward; depth class re-verified against the PDF by DEP-2",
            extra={"obs_dates_note": f"source gives the monsoon YEAR only; obs range set to the calendar year {yr} (weakest true statement), not to a date",
                   "positional_accuracy_note": "per-record uncertainty radius 50-750 m by placement precision (street/place/office/locality); a single value is not defensible so positional_accuracy_m is null"})
        mp = refdir / f"REF-{yr}-CDMP_points.reference_meta.json"
        write_json(mp, meta)
        refs.append((f, mp))
    g = gpd.read_file(c.A / "osmin_flooded_streets_2015_dec2.gpkg")
    g = g[~g.dup_osm_id & ~g.outside_chennai_region].copy()
    g["geometry"] = g.geometry.representative_point()
    f = refdir / "REF-2015-OSMIN-DEC2_points.geojson"
    if f.exists():
        f.unlink()
    g[["osm_id", "type", "class", "geometry"]].to_crs(GEO_CRS).to_file(f, driver="GeoJSON")
    meta = reference.checker_sidecar(
        "REF-2015-OSMIN-DEC2", "Crowd-sourced flooded streets, Chennai, dump 2015-12-02 11:00 IST (one point per street segment)", "osm-in community (anonymous public contributions)",
        "https://github.com/osm-in/flood-map @5790681 data/chennai-flooded-streets-Dec2.geojson", obtained, "MIT (code); OpenStreetMap-derived geometry, ODbL 1.0 (attribution required)", True,
        "points", "2015-11-20", "2015-12-02", True, False, None,
        {"1": "street segment flagged as flooded by a member of the public (presence only)", "0": "NOT DEFINED"},
        "Public flagged OSM street segments on a web map; anonymous, no per-report timestamp; converted to one representative point per segment for the checker (lines are not a supported kind)",
        extra={"obs_dates_note": "start date 2015-11-20 is the repository's Chennai README update (lower bound of contributions is UNCERTAIN); end = dump time"})
    mp = refdir / "REF-2015-OSMIN-DEC2_points.reference_meta.json"
    write_json(mp, meta)
    refs.append((f, mp))
    # ---- R0/R1/R2 via the project's unmodified checker
    ch = c.cfg["checker"]
    root = c.rp(ch["repo_root"])
    if ch["aoi_mode"] == "substitute_gcc_wards":
        _harness_aoi(c, root)
    runs = []
    for f, mp in refs:
        od = c.A / "checker_runs" / f.stem
        if od.exists():
            shutil.rmtree(od)
        rc = reference.run_checker_harness(root, f, mp, od, time.strftime("%Y-%m-%d"))
        r2 = read_json(od / "R2_readiness.json") if (od / "R2_readiness.json").is_file() else {}
        runs.append({"reference": f.stem, "exit_code": rc, "aoi_mode": ch["aoi_mode"], "primary_class": r2.get("primary_class"),
                     "candidate_label": (r2.get("candidate_label_comparison") or {}).get("verdict"),
                     "candidate_label_blockers": " | ".join((r2.get("candidate_label_comparison") or {}).get("blockers", [])),
                     "presence_only": (r2.get("presence_only_comparison") or {}).get("verdict"),
                     "presence_only_blockers": " | ".join((r2.get("presence_only_comparison") or {}).get("blockers", [])),
                     "qualitative": (r2.get("qualitative_comparison") or {}).get("verdict"),
                     "intake_status": r2.get("intake_status"), "alignment_status": r2.get("alignment_status")})
    write_csv(pd.DataFrame(runs), c.A / "R0_R1_R2_summary.csv")
    # supplementary R1 temporal check for the 2015 references against the 2015 Sentinel-1 dates, using the checker's own temporal() function
    import importlib
    sys.path.insert(0, str(root))
    RI = importlib.import_module("src.flood_detection.ref_integration")
    s1_2015 = ["2015-11-12", "2015-11-24", "2015-12-06", "2015-12-18"]
    tt = []
    for rid, rng in (("REF-2015-CDMP", ("2015-01-01", "2015-12-31")), ("REF-2015-OSMIN-DEC2", ("2015-11-20", "2015-12-02"))):
        off, _ = RI.temporal(rng, s1_2015)
        tt.append(off.assign(reference=rid))
    sys.path.remove(str(root))
    write_csv(pd.concat(tt), c.A / "R1_supplementary_temporal_2015_vs_s1_2015.csv")
    # ---- comparisons (presence-only, event-specific, null-model based)
    cc = c.cfg["comparison"]
    wards = c.wards
    roads = layers.read_gz_geojson(c.src.tngis / "gcc_roads.geojson.gz").to_crs(ANALYSIS_CRS)
    comps = reference.load_s1_components(c.rp(c.cfg["s1_components_csv"]))
    grid_check = reference.verify_grid_origin(comps)
    write_json(c.A / "s1_grid_origin_check.json", grid_check)
    region = wards.union_all().intersection(reference.grid_extent_polygon())
    sets = {s: comps[comps.set == s] for s in c.cfg["s1_component_sets"]}
    rep21 = loc[(loc.year == 2021) & loc.placed].copy()
    rep21["geometry"] = rep21.geometry.representative_point()
    t1 = reference.compare_reports_to_components(rep21, sets, roads, region, tuple(cc["component_thresholds_m"]), cc["null_draws"], cc["seed"])
    t1.insert(0, "comparison", "EV-2021-01 (CDMP 2021, E3) vs S1PE bright-VV components (E4) - presence-only, exploratory")
    write_csv(t1, c.A / "comparison_2021_cdmp_vs_s1_brightvv.csv")
    rep15 = loc[(loc.year == 2015) & loc.placed].copy()
    rep15_pts = rep15.copy()
    rep15_pts["geometry"] = rep15_pts.geometry.representative_point()
    osm2 = gpd.read_file(c.A / "osmin_flooded_streets_2015_dec2.gpkg")
    osm2 = osm2[~osm2.dup_osm_id & ~osm2.outside_chennai_region]
    t2a = reference.compare_report_sets(rep15_pts, osm2, roads, region=wards.union_all(), buffers=tuple(cc["report_buffer_m"]), n_null=cc["null_draws"], seed=cc["seed"],
                                        label_a="EV-2015-01 CDMP 2015 (points)", label_b="EV-2015-02 osm-in flooded streets 2 Dec 2015")
    osm_pts = osm2.copy()
    osm_pts["geometry"] = osm_pts.geometry.representative_point()
    t2b = reference.compare_report_sets(osm_pts, rep15, roads, region=wards.union_all(), buffers=tuple(cc["report_buffer_m"]), n_null=cc["null_draws"], seed=cc["seed"],
                                        label_a="EV-2015-02 osm-in street points", label_b="EV-2015-01 CDMP 2015 geometries")
    write_csv(pd.concat([t2a, t2b]), c.A / "comparison_2015_cdmp_vs_osmin.csv")
    # ward-level reported-location counts (ALL records incl. unplaced; ward is printed in the source)
    allrec = loc.drop(columns="geometry")
    allrec["ward_no"] = pd.to_numeric(allrec.ward, errors="coerce")
    wc = allrec.pivot_table(index="ward_no", columns="year", values="row_id", aggfunc="count", fill_value=0)
    wc.columns = [f"cdmp_records_{y}" for y in wc.columns]
    wc["cdmp_years_listed"] = (wc > 0).sum(axis=1)
    osm_w = gpd.sjoin(osm_pts[["geometry"]], wards[["ward_no", "geometry"]], predicate="within").groupby("ward_no").size().rename("osmin_streets_2015_dec2")
    wt = wards[["ward_no", "zone_no", "area_km2"]].merge(wc.reset_index(), on="ward_no", how="left").merge(osm_w.reset_index(), on="ward_no", how="left").fillna(0)
    write_csv(wt, c.A / "ward_reported_inundation_counts.csv")
    # recurrence 2015 -> 2021 (same ward + same printed location name)
    k15 = set(zip(allrec[allrec.year == 2015].ward_no, allrec[allrec.year == 2015].location.str.lower().str.strip()))
    k21 = set(zip(allrec[allrec.year == 2021].ward_no, allrec[allrec.year == 2021].location.str.lower().str.strip()))
    w15, w21 = set(wt[wt.cdmp_records_2015 > 0].ward_no), set(wt[wt.cdmp_records_2021 > 0].ward_no)
    write_json(c.A / "recurrence_2015_2021.json", {"locations_2015": len(k15), "locations_2021": len(k21), "same_name_same_ward_in_both": len(k15 & k21),
                                                   "wards_2015": len(w15), "wards_2021": len(w21), "wards_both": len(w15 & w21),
                                                   "note": "Name matching is exact after lower-casing; spelling variants are NOT merged, so recurrence is a lower bound. Descriptive only; 2015 does not validate 2021."})
    LOG.info("reference stage done")


def st_exposure(c: Ctx):
    import geopandas as gpd
    wards = c.wards
    pop, chk = layers.ward_population(c.src, wards)
    write_csv(chk, c.B / "population_cdmp_zone_reconciliation.csv")
    write_csv(pop, c.B / "population_cdmp_by_ward.csv")
    fac = exposure.facility_inventory(c.src, wards)
    write_gpkg(fac, c.B / "critical_facility_inventory.gpkg", "facilities")
    write_csv(fac.drop(columns="geometry").assign(x=fac.geometry.x, y=fac.geometry.y), c.B / "critical_facility_inventory.csv")
    rt, rp, ol = exposure.roads(c.src, wards)
    wp, wpinfo = exposure.worldpop_zonal(c.src, wards)
    write_csv(wp, c.B / "population_worldpop2020_zonal_by_ward.csv")
    write_json(c.B / "population_worldpop2020_info.json", wpinfo)
    loc = gpd.GeoDataFrame(pd.read_pickle(c.int / "cdmp_located.pkl"), geometry="geometry", crs=ANALYSIS_CRS)
    reps = {yr: loc[loc.year == yr] for yr in (2015, 2021)}
    t = exposure.exposure_table(wards, pop, rt, wp, fac, reps, c.cfg["exposure"]["near_reported_radius_m"])
    # population (WorldPop cells, complete wards only) within the reported-location zone
    import rasterio
    with rasterio.open(c.src.worldpop) as d:
        a = d.read(1).astype(float)
        tr, nd = d.transform, d.nodata
    rr, cc_ = np.nonzero((a != nd) & np.isfinite(a))
    cells = gpd.GeoDataFrame({"pop": a[rr, cc_]}, geometry=gpd.points_from_xy(tr.c + (cc_ + 0.5) * tr.a, tr.f + (rr + 0.5) * tr.e), crs=ANALYSIS_CRS)
    for yr, rep in reps.items():
        cells[f"near_{yr}"] = exposure.near_reported(cells, rep[rep.placed], c.cfg["exposure"]["near_reported_radius_m"])
    cells = gpd.sjoin(cells, wards[["ward_no", "geometry"]], predicate="within", how="left").drop(columns="index_right")
    for yr in reps:
        s = cells[cells[f"near_{yr}"]].groupby("ward_no")["pop"].sum().rename(f"wp_pop_near_reported_{yr}")
        t = t.merge(s.reset_index(), on="ward_no", how="left")
        t.loc[t.wp_coverage_flag != "COMPLETE", f"wp_pop_near_reported_{yr}"] = np.nan
        t.loc[(t.wp_coverage_flag == "COMPLETE") & t[f"wp_pop_near_reported_{yr}"].isna(), f"wp_pop_near_reported_{yr}"] = 0.0
    # road surface within the reported-location zone
    for yr, rep in reps.items():
        r = rep[rep.placed]
        zone = r.geometry.buffer(c.cfg["exposure"]["near_reported_radius_m"] + r.position_uncertainty_m.values).union_all()
        ri = gpd.overlay(rp[["geometry"]], gpd.GeoDataFrame(geometry=[zone], crs=ANALYSIS_CRS), how="intersection", keep_geom_type=True)
        ri = gpd.overlay(ri, wards[["ward_no", "geometry"]], how="intersection", keep_geom_type=True)
        t = t.merge(ri.assign(a=ri.area).groupby("ward_no").a.sum().rename(f"road_surface_near_reported_{yr}_m2").reset_index(), on="ward_no", how="left")
        t[f"road_surface_near_reported_{yr}_m2"] = t[f"road_surface_near_reported_{yr}_m2"].fillna(0.0)
    write_csv(t, c.B / "exposure_indicators_by_ward.csv")
    wg = wards[["ward_no", "geometry"]].merge(t, on="ward_no")
    write_gpkg(wg, c.B / "exposure_by_ward.gpkg", "exposure_wards")
    write_gpkg(rp.assign(source="TNGIS gcc_road_of_width")[["road_name", "ward_no", "source", "geometry"]] if "ward_no" in rp else rp, c.B / "road_surface_tngis.gpkg", "road_surface")
    write_gpkg(ol[["name", "highway", "geometry"]], c.B / "roads_osm_named.gpkg", "osm_named_roads")
    cells.to_pickle(c.int / "wp_cells.pkl")
    top = t.sort_values("exposure_index_provisional", ascending=False).head(20)[["ward_no", "zone_no", "population_cdmp", "population_density_cdmp_per_km2", "road_surface_share",
                                                                                  "n_critical_facilities", "exposure_index_provisional"]]
    write_csv(top, c.B / "top20_exposed_wards_provisional_index.csv")
    LOG.info("exposure stage done")


def st_vulnerability(c: Ctx):
    import geopandas as gpd
    wards = c.wards
    pop = pd.read_csv(c.B / "population_cdmp_by_ward.csv")
    slums = gpd.read_file(c.src.slums)
    health = layers.read_gz_geojson(c.src.tngis / "health_facilities.geojson.gz")
    relief = pd.read_csv(c.src.relief_csv)
    t = vulnerability.indicators(wards, pop, slums, health, relief, c.src.worldpop)
    ok = t[vulnerability.USED].notna().all(axis=1)
    norm = vulnerability.normalise(t[ok], vulnerability.USED)
    comp, idx = vulnerability.components(norm)
    out = t.copy()
    for col in vulnerability.USED:
        out.loc[ok, f"{col}_norm"] = norm[col]
    for col in comp.columns:
        out.loc[ok, f"component_{col}"] = comp[col]
    out.loc[ok, "vulnerability_index_provisional"] = idx
    out["vulnerability_rank"] = out.vulnerability_index_provisional.rank(ascending=False, method="min")
    out["data_complete"] = ok
    write_csv(out, c.C / "vulnerability_indicators_components_by_ward.csv")
    write_gpkg(wards[["ward_no", "geometry"]].merge(out, on="ward_no"), c.C / "vulnerability_by_ward.gpkg", "vulnerability_wards")
    sens, corr, _ = vulnerability.sensitivity(t, c.cfg["vulnerability"]["dirichlet_draws"], 20261128, c.cfg["vulnerability"]["top_k"])
    write_csv(sens, c.C / "vulnerability_sensitivity.csv")
    write_csv(corr.reset_index().rename(columns={"index": "indicator"}), c.C / "vulnerability_indicator_correlation_spearman.csv")
    write_csv(pd.DataFrame([{"indicator": k, "component": v[0], "direction": v[1], "definition": v[2], "source": v[3], "used": k in vulnerability.USED}
                            for k, v in vulnerability.INDICATORS.items()]), c.C / "vulnerability_indicator_definitions.csv")
    write_csv(pd.DataFrame(vulnerability.MISSING, columns=["indicator", "component", "why_missing"]), c.C / "vulnerability_missing_indicators.csv")
    write_json(c.C / "vulnerability_weights_normalisation.json", {"normalisation": "min-max over wards with complete data; protective indicators inverted",
                                                                    "within_component": "equal weights", "between_components": "equal weights (1/2 each: housing, adaptive capacity) - an ASSUMPTION, not optimised; social sensitivity component MISSING",
                                                                    "missing_data": "wards with any missing indicator get NO composite (never imputed)",
                                                                    "indicators_used": vulnerability.USED})
    rank = out[ok].sort_values("vulnerability_index_provisional", ascending=False)[["ward_no", "zone_no", "vulnerability_index_provisional", "vulnerability_rank"] + [f"component_{x}" for x in comp.columns]]
    write_csv(rank, c.C / "vulnerability_ranking.csv")
    LOG.info("vulnerability stage done")


def st_integrate(c: Ctx):
    wards = c.wards
    e = pd.read_csv(c.B / "exposure_indicators_by_ward.csv")
    v = pd.read_csv(c.C / "vulnerability_indicators_components_by_ward.csv")
    r = pd.read_csv(c.A / "ward_reported_inundation_counts.csv")
    t = wards[["ward_no", "zone_no", "area_km2"]].merge(r.drop(columns=["zone_no", "area_km2"]), on="ward_no").merge(
        e[["ward_no", "population_cdmp", "population_density_cdmp_per_km2", "n_critical_facilities", "exposure_index_provisional",
           "n_facilities_near_reported_2015", "n_facilities_near_reported_2021"]], on="ward_no", how="left").merge(
        v[["ward_no", "vulnerability_index_provisional", "component_housing_built_environment", "component_adaptive_capacity"]], on="ward_no", how="left")
    t["reported_2021_per_km2"] = t.cdmp_records_2021 / t.area_km2
    t["reported_2015_per_km2"] = t.cdmp_records_2015 / t.area_km2

    def terc(s):
        return pd.qcut(s.rank(method="first"), 3, labels=["low", "mid", "high"]).astype(str).where(s.notna(), "not assessed")
    t["reported_2021_tercile"] = terc(t.reported_2021_per_km2)
    t["exposure_tercile"] = terc(t.exposure_index_provisional)
    t["vulnerability_tercile"] = terc(t.vulnerability_index_provisional)
    t["priority_profile_exploratory"] = t.reported_2021_tercile + "/" + t.exposure_tercile + "/" + t.vulnerability_tercile
    t["all_three_high_exploratory"] = (t.reported_2021_tercile == "high") & (t.exposure_tercile == "high") & (t.vulnerability_tercile == "high")
    write_csv(t, c.D / "integrated_ward_comparison.csv")
    from scipy.stats import spearmanr
    cols = ["reported_2021_per_km2", "reported_2015_per_km2", "population_density_cdmp_per_km2", "exposure_index_provisional", "vulnerability_index_provisional",
            "component_housing_built_environment", "component_adaptive_capacity"]
    m = t[cols].dropna()
    cm = pd.DataFrame([[spearmanr(m[a], m[b]).statistic for b in cols] for a in cols], index=cols, columns=cols)
    write_csv(cm.reset_index().rename(columns={"index": "variable"}), c.D / "integrated_correlation_spearman.csv")
    pri = t[t.all_three_high_exploratory].sort_values("reported_2021_per_km2", ascending=False)
    write_csv(pri, c.D / "wards_high_on_reported_exposure_vulnerability_exploratory.csv")
    write_gpkg(wards[["ward_no", "geometry"]].merge(t, on="ward_no"), c.D / "integrated_ward_comparison.gpkg", "integrated_wards")
    LOG.info("integrate stage done: %d wards high on all three (exploratory)", len(pri))


def st_maps(c: Ctx):
    import geopandas as gpd
    w = c.wards
    A, F = c.A, c.F
    b = w.total_bounds
    maps.EXTENT = (b[0] - 3000, b[1] - 9000, b[2] + 3000, b[3] + 1500)
    loc = gpd.GeoDataFrame(pd.read_pickle(c.int / "cdmp_located.pkl"), geometry="geometry", crs=ANALYSIS_CRS)
    src_cdmp = "GCC City Disaster Management Plan 2026 (inundation tables, depth classes re-verified by DEP-2); placement: reclaimchennai gazetteer @56c3a6a; wards: TNGIS"
    for yr in (2015, 2021):
        fig, ax = maps.base_axes(f"Reported inundation locations, monsoon {yr} (GCC CDMP)", "REPORTED administrative locations (E3) - presence only; unplaced records not drawn; absence of a point is NOT absence of flooding")
        w.plot(ax=ax, color="#f7f7f7", edgecolor="#bbb", linewidth=0.3)
        g = loc[(loc.year == yr) & loc.placed].copy()
        g["geometry"] = g.geometry.representative_point()
        cols = {"very_high": "#67000d", "high": "#cb181d", "medium": "#fb6a4a", "low": "#fcbba1"}
        from matplotlib.lines import Line2D
        hs = []
        for k, col in cols.items():
            s = g[g.depth_class_verified == k]
            if len(s):
                s.plot(ax=ax, color=col, markersize=9, edgecolor="black", linewidth=0.2)
            hs.append(Line2D([], [], marker="o", ls="", color=col, markeredgecolor="black", label=f"{cdmp.DEPTH_LABELS[k]} ({len(s)})"))
        s = g[g.depth_class_verified.isna()]
        if len(s):
            s.plot(ax=ax, color="white", markersize=9, edgecolor="black", linewidth=0.4)
        hs.append(Line2D([], [], marker="o", ls="", color="white", markeredgecolor="black", label=f"depth not verified ({len(s)})"))
        hs.append(Line2D([], [], ls="", label=f"unplaced (not drawn): {int(((loc.year == yr) & ~loc.placed).sum())}"))
        w.dissolve().boundary.plot(ax=ax, color="black", linewidth=0.8)
        maps.furniture(ax, src_cdmp, f"monsoon {yr} (year only; no dates in source)", "REPORTED (E3)", extra_legend=hs, legend_title="Printed depth class")
        maps.save(fig, F / f"map_A1_reported_inundation_{yr}.png")
    # 2015 two-source map
    fig, ax = maps.base_axes("December 2015: two independent REPORTED sources", "GCC CDMP 2015 locations (E3) and crowd-flagged streets to 2 Dec 2015 11:00 IST (E3); neither is a flood extent")
    w.plot(ax=ax, color="#f7f7f7", edgecolor="#bbb", linewidth=0.3)
    o = gpd.read_file(A / "osmin_flooded_streets_2015_dec2.gpkg")
    o = o[~o.outside_chennai_region]
    o.plot(ax=ax, color="#2171b5", linewidth=0.8)
    g = loc[(loc.year == 2015) & loc.placed].copy()
    g["geometry"] = g.geometry.representative_point()
    g.plot(ax=ax, color="#cb181d", markersize=7, edgecolor="black", linewidth=0.2)
    from matplotlib.lines import Line2D
    hs = [Line2D([], [], color="#2171b5", label=f"crowd-flagged street (osm-in, {len(o)})"), Line2D([], [], marker="o", ls="", color="#cb181d", label=f"GCC CDMP 2015 location ({len(g)})")]
    w.dissolve().boundary.plot(ax=ax, color="black", linewidth=0.8)
    maps.furniture(ax, "osm-in/flood-map @5790681 (OSM ODbL); GCC CDMP 2026; TNGIS wards", "2015 monsoon; crowd dump 2015-12-02 11:00 IST", "REPORTED (E3)", extra_legend=hs)
    maps.save(fig, F / "map_A2_2015_two_reported_sources.png")
    # coverage map: grid extent vs wards vs CDMP vs S1 components
    fig, ax = maps.base_axes("Reference-data coverage", "Analysis grid extent (from S1 tables), GCC wards, placed 2021 reports and 28 Nov 2021 bright-VV components (E4, NOT floodwater)")
    w.plot(ax=ax, color="#f0f0f0", edgecolor="#bbb", linewidth=0.3)
    gpd.GeoSeries([reference.grid_extent_polygon()], crs=ANALYSIS_CRS).boundary.plot(ax=ax, color="purple", linestyle="--")
    comps = reference.load_s1_components(c.rp(c.cfg["s1_components_csv"]))
    cm = comps[comps.set == "2021-11-28"]
    cm.plot(ax=ax, markersize=1, color="#41ab5d", alpha=0.6)
    g = loc[(loc.year == 2021) & loc.placed].copy()
    g["geometry"] = g.geometry.representative_point()
    g.plot(ax=ax, markersize=8, color="#cb181d", edgecolor="black", linewidth=0.2)
    hs = [Line2D([], [], color="purple", ls="--", label="30 m master-grid extent (derived)"), Line2D([], [], marker=".", ls="", color="#41ab5d", label=f"bright-VV component 28 Nov 2021 ({len(cm)})"),
          Line2D([], [], marker="o", ls="", color="#cb181d", label=f"CDMP 2021 placed location ({len(g)})")]
    maps.furniture(ax, "project S1PE tables; GCC CDMP 2026; TNGIS", "2021 monsoon; S1 28 Nov 2021 06:01 IST", "REPORTED (E3) vs SATELLITE-DERIVED CANDIDATE (E4)", extra_legend=hs)
    maps.save(fig, F / "map_A3_reference_coverage_and_s1_candidates_2021.png")
    # exposure maps
    e = w.merge(pd.read_csv(c.B / "exposure_indicators_by_ward.csv").drop(columns=["zone_no", "area_km2", "zone_label", "region"], errors="ignore"), on="ward_no", how="left")
    maps.choropleth(e, "population_density_cdmp_per_km2", "Population density by ward (persons/km²)", "EXPOSURE quantity - ward totals printed in GCC CDMP 2026 (reference year not stated); not vulnerability",
                    "GCC CDMP 2026 ward population tables; TNGIS wards", "reference year not stated in source", "ADMINISTRATIVE (tabulated)", F / "map_B1_population_density.png", fmt="{:,.0f}")
    fac = gpd.read_file(c.B / "critical_facility_inventory.gpkg")
    maps.choropleth(e, "road_surface_share", "Road surface share of ward area + critical facilities", "EXPOSURE - TNGIS road-surface polygons; points = facilities (TNGIS public health, schools, police, shelters, GCC offices; CDMP relief centres)",
                    "TNGIS WFS layers via reclaimchennai @56c3a6a; GCC CDMP 2026", "TNGIS download Oct 2026 (snapshot)", "ADMINISTRATIVE GIS (mapped assets)", F / "map_B2_roads_and_facilities.png",
                    cmap="Greys", points=fac[~fac.duplicate_location_same_class & fac.ward_no.notna()], point_kw={"markersize": 1.5, "color": "#08519c"}, point_label=f"critical facility inside GCC ({int((~fac.duplicate_location_same_class & fac.ward_no.notna()).sum())})")
    maps.choropleth(e, "exposure_index_provisional", "Provisional exposure index (ward)", "EXPLORATORY: mean of min-max scores of population density, road-surface share, facility density; equal weights (assumption)",
                    "derived (see B_exposure)", "mixed: CDMP (year not stated), TNGIS Oct 2026", "DERIVED INDEX (exploratory)", F / "map_B3_exposure_index_provisional.png", cmap="Purples")
    e2 = e.copy()
    e2["wp_population_2020_density"] = e2.wp_population_2020 / e2.area_km2
    maps.choropleth(e2, "wp_population_2020_density", "WorldPop 2020 (constrained, 100 m) population density - covered wards only", "Grey = ward not fully covered by the available WorldPop clip (NOT zero); 100 m modelled data, not 30 m precision",
                    "WorldPop R2025A ind_pop_2020_CN_100m (CC BY 4.0) as clipped by km658 @e9abb98", "2020 (modelled)", "MODELLED (gridded population)", F / "map_B4_worldpop2020_density_covered_wards.png", fmt="{:,.0f}")
    v = w.merge(pd.read_csv(c.C / "vulnerability_indicators_components_by_ward.csv").drop(columns=["zone_no", "area_km2"], errors="ignore"), on="ward_no", how="left")
    for col, ttl in (("component_housing_built_environment", "Vulnerability component: housing (slum area share)"),
                     ("component_adaptive_capacity", "Vulnerability component: low adaptive capacity (health access, relief capacity)"),
                     ("vulnerability_index_provisional", "Partial vulnerability index: housing + adaptive capacity (social sensitivity MISSING)")):
        maps.choropleth(v, col, ttl, "EXPLORATORY normalised score 0-1 (higher = more vulnerable); several standard indicators MISSING (see C_vulnerability)",
                        "GCC CDMP 2026; slum polygons (provenance unresolved); TNGIS health facilities", "mixed vintages (see register)", "DERIVED INDEX (exploratory)",
                        F / f"map_C_{col}.png", cmap="OrRd")
    it = w.merge(pd.read_csv(c.D / "integrated_ward_comparison.csv").drop(columns=["zone_no", "area_km2"]), on="ward_no", how="left")
    fig, ax = maps.base_axes("Integrated analytical overview (exploratory)", "Wards shaded by how many of {reported-2021 density, exposure, vulnerability} are in the top tercile; NOT a risk score, NOT validated")
    it["n_high"] = (it[["reported_2021_tercile", "exposure_tercile", "vulnerability_tercile"]] == "high").sum(axis=1)
    it.loc[it.vulnerability_tercile == "not assessed", "n_high"] = np.nan
    cmap = maps.plt.get_cmap("Reds", 4)
    from matplotlib.patches import Patch
    hs = []
    for k in range(4):
        s = it[it.n_high == k]
        if len(s):
            s.plot(ax=ax, color=cmap(k), edgecolor="white", linewidth=0.3)
        hs.append(Patch(facecolor=cmap(k), label=f"{k} of 3 in top tercile ({len(s)} wards)"))
    s = it[it.n_high.isna()]
    if len(s):
        s.plot(ax=ax, color=maps.NODATA_COLOR, edgecolor="#999", hatch="///", linewidth=0.3)
    hs.append(maps.nodata_patch())
    it.dissolve().boundary.plot(ax=ax, color="black", linewidth=0.8)
    maps.furniture(ax, "DEP-2 derived (A, B, C sections)", "2021 monsoon reports; exposure/vulnerability mixed vintages", "DERIVED COMPARISON (exploratory; components kept separate)", extra_legend=hs)
    maps.save(fig, F / "map_D1_integrated_overview_exploratory.png")
    LOG.info("maps written: %d", len(list(F.glob("*.png"))))


def st_contract(c: Ctx):
    from dep2 import mlcontract
    mlcontract.write_all(c)


def st_sus1overlay(c: Ctx):
    """Exposure in SUS-1 top-decile cells (read-only on SUS-1). Runs only where outputs/susceptibility_v1 exists."""
    import geopandas as gpd
    import rasterio
    from dep2 import sus1_overlay
    sp = c.rp("outputs/susceptibility_v1/rasters/susceptibility_percentile.tif")
    dp = c.rp("outputs/susceptibility_v1/rasters/domain_class.tif")
    if not (sp.is_file() and dp.is_file()):
        LOG.warning("SUS-1 rasters not found (%s); sus1overlay skipped - run on the project machine", sp)
        write_json(c.D / "sus1_overlay_NOT_RUN.json", {"reason": "SUS-1 rasters not present in this environment", "expected": [str(sp), str(dp)]})
        return
    h0 = {str(p): sha256_file(p) for p in (sp, dp)}
    pct, dom, tr = sus1_overlay.read_sus1(sp, dp)
    with rasterio.open(c.src.worldpop) as d:
        wp = (d.read(1).astype(float), d.transform, d.nodata)
    fac = gpd.read_file(c.B / "critical_facility_inventory.gpkg")
    t, f = sus1_overlay.overlay(pct, dom, tr, c.wards, fac[~fac.duplicate_location_same_class], wp, 90.0)
    write_csv(t, c.D / "sus1_top_decile_exposure_by_ward.csv")
    write_csv(f.drop(columns="geometry")[["facility_id", "facility_class", "ward_no", "sus1_cell_state"]], c.D / "sus1_facility_cell_state.csv")
    h1 = {str(p): sha256_file(p) for p in (sp, dp)}
    write_json(c.D / "sus1_overlay_inputs_unchanged.json", {"before": h0, "after": h1, "unchanged": h0 == h1})


def st_manifest(c: Ctx):
    """run_manifest.json first, then SHA256SUMS.txt over everything except logs (which keep growing)."""
    n_files = sum(1 for q in c.out.rglob("*") if q.is_file() and q.name != "SHA256SUMS.txt" and "logs" not in q.relative_to(c.out).parts)
    write_json(c.out / "run_manifest.json", {"version": VERSION, "finished_utc": utcnow(), "config": c.cfg, "config_sha256": sha256_file(c.cfg_path),
                                              "environment": environment(), "files_hashed_in_SHA256SUMS": n_files + 1,
                                              "acquisition_log_sha256": sha256_file(c.raw / "ACQUISITION_LOG.json")})
    manifest(c.out, c.out / "SHA256SUMS.txt", exclude=("SHA256SUMS.txt",))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=STAGES + OPTIONAL + ["all"])
    ap.add_argument("--config", default=str(ROOT / "config" / "dep2.json"))
    a = ap.parse_args(argv)
    c = Ctx(Path(a.config))
    setup_logging(c.out / "logs" / "dep2_run.log")
    LOG.info("DEP-2 %s stage=%s config=%s", VERSION, a.stage, a.config)
    todo = (STAGES[:-1] + OPTIONAL + STAGES[-1:]) if a.stage == "all" else [a.stage]
    for s in todo:
        t0 = time.time()
        globals()[f"st_{s}"](c)
        LOG.info("stage %s finished in %.1f s", s, time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
