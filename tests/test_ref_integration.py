"""Flood-reference integration R0-R2 tests. SYNTHETIC fixtures only: no real reference data, no network, no Earth Engine/ASF/Copernicus. Software validation here is not flood-map accuracy validation."""
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, Polygon, box
from src.flood_detection import ref_integration as RI
from src.geospatial.grid import make_master_grid

AOI = box(80.18, 13.00, 80.19, 13.01)
GRID = make_master_grid(gpd.GeoSeries([AOI], crs=4326).to_crs(32644).total_bounds)
DATES = ["2021-09-05", "2021-09-17", "2021-09-29", "2021-10-11", "2021-10-23", "2021-11-04", "2021-11-16", "2021-11-28"]
TODAY = date(2026, 11, 26)
spec = importlib.util.spec_from_file_location("ref_check", ROOT / "scripts" / "reference_integration_check.py"); SC = importlib.util.module_from_spec(spec); spec.loader.exec_module(SC)


def meta(**kw):
    m = {"reference_id": "synthetic_ref", "name": "SYNTHETIC test reference", "producer": "unit test", "source": "generated in test", "obtained_on": "2026-11-20", "licence": "test only", "licence_permits_derived_stats": True,
         "kind": "extent_raster", "obs_date": "2021-11-05", "obs_time_of_day": "06:00", "sensor_family": "test", "independent_of_s1": True, "production_method_documented": True, "method_summary": "synthetic",
         "positional_accuracy_m": 10, "class_meaning": {"1": "flooded", "0": "not flooded"}}
    m.update(kw); return {k: v for k, v in m.items() if v is not RI.UNK or True}


def raster(path, arr=None, crs=None, transform=None, nodata=255, dtype="uint8"):
    crs = crs if crs is not None else GRID.crs; transform = transform or GRID.transform
    if arr is None: arr = np.zeros(GRID.shape, dtype); arr[5:20, 5:20] = 1
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=arr.dtype, crs=crs, transform=transform, nodata=nodata) as ds: ds.write(arr, 1)
    return Path(path)


def poly_file(path, geoms=None, crs=4326, driver=None):
    geoms = geoms or [AOI.buffer(0.01)]; gdf = gpd.GeoDataFrame({"c": [1] * len(geoms)}, geometry=geoms, crs=crs); gdf.to_file(path, driver=driver or ("GPKG" if str(path).endswith(".gpkg") else "ESRI Shapefile" if str(path).endswith(".shp") else "GeoJSON")); return Path(path)


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self): self.t = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.t, True)
    def codes(self, rep, level=None): return sorted({f["code"] for f in rep["findings"] if level is None or f["level"] == level})
    def lvl(self, rep, code): return next(f["level"] for f in rep["findings"] if f["code"] == code)
    def r0(self, path, m=None, **kw): return RI.intake(path, meta(**kw) if m is None else m, AOI, TODAY)


class TestR0(Base):
    def test_valid_raster_passes_without_claiming_authority(self):
        p = raster(self.t / "a.tif"); h = sha(p); r = self.r0(p); self.assertEqual(r["status"], RI.PASS, [f for f in r["findings"] if f["level"] != RI.PASS]); self.assertTrue(r["unchanged"]); self.assertEqual(sha(p), h)
        self.assertIn("NOT flood-map accuracy validation", r["statement"]); self.assertIn("does not make it an authoritative", r["statement"])

    def test_missing_empty_malformed_unsupported_files(self):
        r = self.r0(self.t / "nope.tif"); self.assertEqual(r["status"], RI.FAIL); self.assertIn("FILE", self.codes(r, RI.FAIL))
        (self.t / "e.tif").write_bytes(b""); self.assertIn("FILE", self.codes(self.r0(self.t / "e.tif"), RI.FAIL))
        (self.t / "bad.tif").write_bytes(b"not a tiff at all" * 20); r = self.r0(self.t / "bad.tif"); self.assertIn("READ", self.codes(r, RI.FAIL)); self.assertTrue(r["unchanged"])
        (self.t / "bad.geojson").write_text("{ this is : not json"); self.assertIn("READ", self.codes(self.r0(self.t / "bad.geojson", kind="extent_polygons"), RI.FAIL))
        (self.t / "map.pdf").write_bytes(b"%PDF-1.4 x"); r = self.r0(self.t / "map.pdf"); self.assertIn("FORMAT", self.codes(r, RI.FAIL)); self.assertIn("qualitative", [f for f in r["findings"] if f["code"] == "FORMAT"][0]["message"])

    def test_metadata_missing_unconfirmed_and_invalid(self):
        p = raster(self.t / "a.tif"); m = meta(); [m.pop(k) for k in ("producer", "licence")]; r = self.r0(p, m); self.assertEqual(r["status"], RI.FAIL)
        f = next(x for x in r["findings"] if x["code"] == "META_FIELDS"); self.assertEqual(sorted(f["evidence"]["missing"]), ["licence", "producer"])
        r = self.r0(p, source="UNCONFIRMED"); self.assertEqual(next(x for x in r["findings"] if x["code"] == "META_FIELDS")["evidence"]["unconfirmed"], ["source"])
        self.assertIn("META_TYPE", self.codes(RI.intake(p, ["not", "a", "dict"], AOI, TODAY), RI.FAIL)); self.assertIn("META_KIND", self.codes(self.r0(p, kind="flood_map"), RI.FAIL))
        self.assertEqual(self.lvl(self.r0(p, independent_of_s1=None), "INDEPENDENCE"), RI.FAIL); self.assertEqual(self.lvl(self.r0(p, independent_of_s1=False), "INDEPENDENCE"), RI.WARN)
        self.assertEqual(self.lvl(self.r0(p, licence_permits_derived_stats=None), "LICENCE"), RI.WARN); self.assertEqual(self.lvl(self.r0(p, positional_accuracy_m=None), "POSITIONAL_ACCURACY"), RI.WARN)

    def test_crs_problems(self):
        p = raster(self.t / "nocrs.tif"); p2 = self.t / "nocrs2.tif"
        with rasterio.open(p2, "w", driver="GTiff", height=4, width=4, count=1, dtype="uint8", transform=from_origin(0, 4, 1, 1)) as ds: ds.write(np.ones((4, 4), "uint8"), 1)
        r = self.r0(p2); self.assertIn("CRS", self.codes(r, RI.FAIL))                                                         # no CRS anywhere
        self.assertIn("CRS", self.codes(self.r0(p, declared_crs="EPSG:99999999"), RI.FAIL))                                  # invalid declared CRS
        self.assertIn("CRS", self.codes(self.r0(p, declared_crs="EPSG:4326"), RI.FAIL))                                      # disagrees with embedded 32644
        self.assertEqual(self.lvl(self.r0(p, declared_crs="EPSG:32644"), "CRS"), RI.PASS)
        r = self.r0(p2, declared_crs="EPSG:32644"); self.assertEqual(self.lvl(r, "CRS"), RI.WARN); self.assertIn("DECLARED ONLY", [f for f in r["findings"] if f["code"] == "CRS"][0]["message"])

    def test_geometry_problems(self):
        bow = Polygon([(80.18, 13.0), (80.19, 13.01), (80.19, 13.0), (80.18, 13.01)]); self.assertFalse(bow.is_valid)
        p = poly_file(self.t / "bow.geojson", [bow]); r = self.r0(p, kind="extent_polygons"); self.assertEqual(next(f for f in r["findings"] if f["code"] == "GEOMETRY")["level"], RI.FAIL); self.assertEqual(next(f for f in r["findings"] if f["code"] == "GEOMETRY")["evidence"]["invalid"], 1)
        mixed = poly_file(self.t / "mix.gpkg", [AOI, Point(80.185, 13.005)]); self.assertIn("GEOMETRY_TYPE", self.codes(self.r0(mixed, kind="extent_polygons"), RI.FAIL))
        far = poly_file(self.t / "far.geojson", [Polygon([(8018, 13), (8019, 13), (8019, 14), (8018, 14)])]); self.assertIn("COORD_RANGE", self.codes(self.r0(far, kind="extent_polygons"), RI.FAIL))
        (self.t / "empty.geojson").write_text('{"type":"FeatureCollection","features":[]}'); r = self.r0(self.t / "empty.geojson", kind="extent_polygons"); self.assertIn("GEOMETRY", self.codes(r, RI.FAIL))
        z = poly_file(self.t / "zero.geojson", [Polygon([(80.18, 13), (80.19, 13), (80.185, 13)])]); self.assertIn("POLYGON_AREA", self.codes(self.r0(z, kind="extent_polygons"), RI.WARN))
        ok = poly_file(self.t / "ok.gpkg"); r = self.r0(ok, kind="extent_polygons"); self.assertEqual(r["status"], RI.PASS, [f for f in r["findings"] if f["level"] != RI.PASS])

    def test_kind_mismatch(self):
        self.assertIn("KIND_MATCH", self.codes(self.r0(raster(self.t / "a.tif"), kind="points"), RI.FAIL))
        self.assertIn("KIND_MATCH", self.codes(self.r0(poly_file(self.t / "p.geojson"), kind="extent_raster"), RI.FAIL))

    def test_dates(self):
        p = raster(self.t / "a.tif")
        for kw, why in ((dict(obs_date=None), "missing"), (dict(obs_date="05/11/2021"), "bad format"), (dict(obs_date="2031-01-01"), "future"), (dict(obs_date_start="2021-11-10", obs_date_end="2021-11-01"), "reversed")):
            m = meta(**kw); [m.pop(k) for k in [k for k, v in m.items() if v is None]]; r = RI.intake(p, m, AOI, TODAY); self.assertEqual(self.lvl(r, "DATE"), RI.FAIL, why)
        r = self.r0(p, obs_date_start="2021-10-01", obs_date_end="2021-11-20"); self.assertEqual(self.lvl(r, "DATE"), RI.WARN)
        m = meta(); m.pop("obs_time_of_day"); self.assertEqual(self.lvl(RI.intake(p, m, AOI, TODAY), "DATE_TIME"), RI.WARN)

    def test_spatial_coverage_levels(self):
        full = self.r0(raster(self.t / "full.tif")); self.assertEqual(self.lvl(full, "SPATIAL_COVERAGE"), RI.PASS)
        half = box(80.185, 12.9, 80.3, 13.1); p = poly_file(self.t / "half.geojson", [half]); r = self.r0(p, kind="extent_polygons"); self.assertEqual(self.lvl(r, "SPATIAL_COVERAGE"), RI.WARN); self.assertAlmostEqual(r["info"]["aoi_footprint_coverage"], 0.5, delta=0.03)
        none = poly_file(self.t / "none.geojson", [box(81.0, 14.0, 81.1, 14.1)]); self.assertEqual(self.lvl(self.r0(none, kind="extent_polygons"), "SPATIAL_COVERAGE"), RI.FAIL)

    def test_raster_content_problems(self):
        r = self.r0(raster(self.t / "allnd.tif", np.full(GRID.shape, 255, "uint8"))); self.assertIn("RASTER_DATA", self.codes(r, RI.FAIL))
        r = self.r0(raster(self.t / "nond.tif", nodata=None)); self.assertIn("RASTER_NODATA", self.codes(r, RI.WARN))
        a = np.zeros(GRID.shape, "uint8"); a[3:9, 3:9] = 7; r = self.r0(raster(self.t / "cls.tif", a)); self.assertIn("CLASS_VALUES", self.codes(r, RI.WARN))
        from affine import Affine
        rot = raster(self.t / "rot2.tif", transform=Affine(30, 2, GRID.transform.c, 0, -30, GRID.transform.f)); self.assertIn("RASTER_ROTATED", self.codes(self.r0(rot), RI.WARN))

    def test_csv_points(self):
        df = pd.DataFrame({"lon": [80.182, 80.185, 80.188], "lat": [13.002, 13.005, 13.008], "depth_cm": [10, 20, 30]}); p = self.t / "pts.csv"; df.to_csv(p, index=False)
        r = self.r0(p, kind="points", declared_crs="EPSG:4326"); self.assertEqual(r["status"], RI.WARN); self.assertEqual(self.codes(r, RI.FAIL), []); self.assertEqual(self.codes(r, RI.WARN), ["CRS", "SPATIAL_COVERAGE"]); self.assertEqual(r["info"]["n_features_in_aoi"], 3)     # declared-only CRS and a points bounding box are WARNINGs, not FAILs
        self.assertIn("CRS", self.codes(self.r0(p, kind="points"), RI.FAIL))                                                   # CSV has no CRS unless declared
        df.assign(lon=["x", 80.1, 80.2]).to_csv(p, index=False); self.assertIn("COORD_VALUES", self.codes(self.r0(p, kind="points", declared_crs="EPSG:4326"), RI.FAIL))
        pd.DataFrame({"a": [1], "b": [2]}).to_csv(p, index=False); self.assertIn("COORD_COLUMNS", self.codes(self.r0(p, kind="points", declared_crs="EPSG:4326"), RI.FAIL))
        pd.DataFrame({"lon": [80.18, 80.18], "lat": [13.0, 13.0]}).to_csv(p, index=False); self.assertIn("DUPLICATE_POINTS", self.codes(self.r0(p, kind="points", declared_crs="EPSG:4326"), RI.WARN))
        pd.DataFrame({"lat": [13.0], "lon": [80.18]}).rename(columns={"lat": "lon", "lon": "lat"}).to_csv(p, index=False)                                   # swapped axes -> latitude 80.18 is valid, lon 13 valid: not detectable (documented limit)
        pd.DataFrame({"lon": [13.0], "lat": [180.5]}).to_csv(p, index=False); self.assertIn("COORD_RANGE", self.codes(self.r0(p, kind="points", declared_crs="EPSG:4326"), RI.FAIL))

    def test_read_only_files_and_no_modification(self):
        p = raster(self.t / "a.tif"); os.chmod(p, stat.S_IREAD); h = sha(p)
        try: r = self.r0(p); self.assertEqual(r["status"], RI.PASS); self.assertEqual(sha(p), h)
        finally: os.chmod(p, stat.S_IWRITE | stat.S_IREAD)


def align(t, path, m=None, dates=DATES, windows=(), **kw):
    r0 = RI.intake(path, meta(**kw) if m is None else m, AOI, TODAY); return r0, RI.alignment(path, r0, AOI, GRID, dates, windows)


class TestR1(Base):
    def test_aligned_raster_is_compatible(self):
        r0, r1 = align(self.t, raster(self.t / "a.tif")); lv = {f["code"]: f["level"] for f in r1["findings"]}
        for c in ("GRID_CRS", "GRID_RES", "GRID_ORIGIN", "AOI_VALID_COVERAGE", "ALIGN_SPATIAL", "ALIGN_TEMPORAL"): self.assertEqual(lv[c], RI.PASS, c)
        self.assertEqual(r1["status"], RI.PASS)

    def test_mismatches_are_reported_not_fixed(self):
        p = raster(self.t / "r10.tif", np.ones((GRID.height * 3, GRID.width * 3), "uint8"), transform=from_origin(GRID.transform.c, GRID.transform.f, 10, 10)); h = sha(p)
        r0, r1 = align(self.t, p); msg = {f["code"]: f["message"] for f in r1["findings"]}; self.assertEqual(r1["status"], RI.WARN); self.assertIn("GRID_RES", self.codes(r1, RI.WARN)); self.assertIn("would need resampling", msg["GRID_RES"]); self.assertIn("(integer multiple)", msg["GRID_RES"]); self.assertEqual(sha(p), h)
        p2 = raster(self.t / "off.tif", transform=from_origin(GRID.transform.c + 7, GRID.transform.f, 30, 30)); _, r1 = align(self.t, p2); self.assertIn("GRID_ORIGIN", self.codes(r1, RI.WARN))
        g = gpd.GeoSeries([AOI], crs=4326).total_bounds; arr = np.ones((200, 200), "uint8")
        p3 = raster(self.t / "wgs.tif", arr, crs="EPSG:4326", transform=from_origin(80.17, 13.02, 0.0002, 0.0002)); _, r1 = align(self.t, p3); m = {f["code"]: f["message"] for f in r1["findings"]}; self.assertIn("no reprojection was performed", m["GRID_CRS"]); self.assertIn("GRID_CRS", self.codes(r1, RI.WARN))
        self.assertEqual(r1["raster_aoi"]["valid_share_of_aoi_cells"], 1.0)                                                      # AOI cells counted on the reference's own grid
        p4 = raster(self.t / "r45.tif", np.ones(GRID.shape, "uint8"), transform=from_origin(GRID.transform.c, GRID.transform.f, 45, 45)); _, r1 = align(self.t, p4); self.assertIn("non-integer", [f for f in r1["findings"] if f["code"] == "GRID_RES"][0]["message"])

    def test_partial_valid_data_inside_aoi(self):
        a = np.ones(GRID.shape, "uint8"); a[:, :GRID.width // 2] = 255; _, r1 = align(self.t, raster(self.t / "half.tif", a)); self.assertEqual(self.lvl(r1, "AOI_VALID_COVERAGE"), RI.WARN); self.assertLess(r1["raster_aoi"]["valid_share_of_aoi_cells"], 0.9)
        _, r1 = align(self.t, raster(self.t / "nov.tif", np.full(GRID.shape, 255, "uint8"))); self.assertEqual(r1["status"], RI.FAIL)

    def test_temporal_offsets_and_event_windows(self):
        p = raster(self.t / "a.tif"); _, r1 = align(self.t, p, windows=[("w_in", "2021-09-05", "2021-11-28"), ("w_out", "2015-11-08", "2015-12-05")])
        t = r1["temporal_df"].set_index("s1_date"); self.assertEqual(t.loc["2021-11-04", "offset_days"], -1); self.assertEqual(t.loc["2021-11-16", "offset_days"], 11); self.assertIn("close", t.loc["2021-11-04", "category"]); self.assertIn("NOT temporally comparable", t.loc["2021-11-16", "category"])
        w = r1["windows_df"].set_index("window"); self.assertTrue(w.loc["w_in", "overlaps_reference_dates"]); self.assertFalse(w.loc["w_out", "overlaps_reference_dates"]); self.assertGreater(w.loc["w_out", "gap_days"], 1000);
        self.assertIn("EVENT_WINDOW", self.codes(r1, RI.WARN))
        _, r1 = align(self.t, p, obs_date="2015-12-03"); self.assertEqual(self.lvl(r1, "ALIGN_TEMPORAL"), RI.FAIL); self.assertEqual(r1["status"], RI.FAIL)           # 2015 reference vs 2021 scenes
        _, r1 = align(self.t, p, obs_date="2021-11-10"); self.assertEqual(r1["min_abs_offset_days"], 6); self.assertEqual(self.lvl(r1, "ALIGN_TEMPORAL"), RI.WARN)
        _, r1 = align(self.t, p, obs_date_start="2021-11-01", obs_date_end="2021-11-06"); self.assertEqual(r1["temporal_df"].set_index("s1_date").loc["2021-11-04", "offset_days"], 0); self.assertEqual(self.lvl(r1, "ALIGN_TEMPORAL"), RI.PASS)
        m = meta(); m.pop("obs_date"); _, r1 = align(self.t, p, m=m); self.assertEqual(self.lvl(r1, "ALIGN_TEMPORAL"), RI.FAIL)

    def test_vector_features_in_aoi_and_unusable_input(self):
        pts = gpd.GeoDataFrame(geometry=[Point(80.185, 13.005), Point(80.5, 13.5)], crs=4326); p = self.t / "p.geojson"; pts.to_file(p, driver="GeoJSON"); r0, r1 = align(self.t, p, kind="points"); self.assertEqual(r1["n_features_in_aoi"], 1); self.assertEqual(self.lvl(r1, "FEATURES_IN_AOI"), RI.PASS)
        far = self.t / "far.geojson"; gpd.GeoDataFrame(geometry=[Point(80.5, 13.5)], crs=4326).to_file(far, driver="GeoJSON"); _, r1 = align(self.t, far, kind="points"); self.assertEqual(self.lvl(r1, "FEATURES_IN_AOI"), RI.FAIL)
        (self.t / "bad.tif").write_bytes(b"xx" * 50); _, r1 = align(self.t, self.t / "bad.tif"); self.assertEqual(self.lvl(r1, "ALIGN_SPATIAL"), RI.FAIL)


class TestR2(Base):
    def run_all(self, path, m=None, dates=DATES, **kw):
        mm = meta(**kw) if m is None else m; r0 = RI.intake(path, mm, AOI, TODAY); r1 = RI.alignment(path, r0, AOI, GRID, dates); return RI.readiness(mm, r0, r1)

    def test_strongest_outcome_is_eligible_for_team_review_not_validated(self):
        r = self.run_all(raster(self.t / "a.tif")); self.assertEqual(r["primary_class"], "CANDIDATE_LABEL_COMPARISON"); self.assertEqual(r["candidate_label_comparison"]["blockers"], []); self.assertIn("ELIGIBLE FOR TEAM REVIEW", r["candidate_label_comparison"]["verdict"])
        self.assertIn("NOT ASSESSED", r["authoritative_reference"]); self.assertIn("NOT flood-map accuracy validation", r["statement"]); self.assertIn("R3 not started", r["candidate_label_comparison"]["verdict"])
        txt = json.dumps(r).lower(); self.assertNotIn("validated reference", txt); self.assertNotIn("ground truth", txt)

    def test_each_candidate_blocker_blocks(self):
        p = raster(self.t / "a.tif")
        for kw, frag in ((dict(independent_of_s1=False), "independence"), (dict(independent_of_s1=None), "independence"), (dict(production_method_documented=False), "method"), (dict(licence_permits_derived_stats=None), "licence"),
                         (dict(positional_accuracy_m=None), "positional"), (dict(class_meaning=None), "class meaning"), (dict(obs_date="2021-11-12"), "within 3 days")):
            m = meta(**kw)
            if kw.get("class_meaning", 1) is None: m.pop("class_meaning")
            r = self.run_all(p, m); self.assertNotEqual(r["primary_class"], "CANDIDATE_LABEL_COMPARISON", kw); self.assertTrue(any(frag in b for b in r["candidate_label_comparison"]["blockers"]), (kw, r["candidate_label_comparison"]["blockers"]))
        a = np.ones(GRID.shape, "uint8"); a[:, :GRID.width // 2] = 255; r = self.run_all(raster(self.t / "half.tif", a)); self.assertTrue(any("valid reference data" in b for b in r["candidate_label_comparison"]["blockers"]))
        r = self.run_all(poly_file(self.t / "half.geojson", [box(80.185, 12.9, 80.3, 13.1)]), kind="extent_polygons"); self.assertTrue(any("AOI coverage" in b for b in r["candidate_label_comparison"]["blockers"]))

    def test_s1_derived_reference_is_consistency_only(self):
        r = self.run_all(raster(self.t / "a.tif"), independent_of_s1=False); self.assertEqual(r["primary_class"], "QUALITATIVE_ONLY"); self.assertIn("consistency comparison only", " ".join(r["candidate_label_comparison"]["blockers"]))

    def test_points_are_presence_only(self):
        p = self.t / "p.geojson"; gpd.GeoDataFrame(geometry=[Point(80.185, 13.005)], crs=4326).to_file(p, driver="GeoJSON")
        r = self.run_all(p, kind="points", obs_date="2021-11-08", class_meaning=None); self.assertEqual(r["primary_class"], "PRESENCE_ONLY"); self.assertIn("absence of a report is NOT absence of flooding", r["presence_only_comparison"]["verdict"])
        self.assertTrue(any("not a mapped flood extent" in b for b in r["candidate_label_comparison"]["blockers"]))
        far = self.t / "far.geojson"; gpd.GeoDataFrame(geometry=[Point(80.5, 13.5)], crs=4326).to_file(far, driver="GeoJSON"); r = self.run_all(far, kind="points"); self.assertNotEqual(r["primary_class"], "PRESENCE_ONLY"); self.assertTrue(any("inside the AOI" in b for b in r["presence_only_comparison"]["blockers"]))

    def test_2015_reference_vs_2021_scenes_is_qualitative_only(self):
        r = self.run_all(raster(self.t / "a.tif"), obs_date="2015-12-03"); self.assertEqual(r["primary_class"], "QUALITATIVE_ONLY"); self.assertEqual(r["qualitative_comparison"]["blockers"], [])
        self.assertTrue(any("closest" in b for b in r["candidate_label_comparison"]["blockers"]))
        p = self.t / "p.geojson"; gpd.GeoDataFrame(geometry=[Point(80.185, 13.005)], crs=4326).to_file(p, driver="GeoJSON"); self.assertNotEqual(self.run_all(p, kind="points", obs_date="2015-12-03")["primary_class"], "PRESENCE_ONLY")

    def test_unusable_when_provenance_or_file_is_bad(self):
        m = meta(); [m.pop(k) for k in ("producer", "source")]; self.assertEqual(self.run_all(raster(self.t / "a.tif"), m)["primary_class"], "UNUSABLE")
        self.assertEqual(self.run_all(self.t / "missing.tif")["primary_class"], "UNUSABLE"); (self.t / "bad.tif").write_bytes(b"zz" * 30); self.assertEqual(self.run_all(self.t / "bad.tif")["primary_class"], "UNUSABLE")
        m = meta(); m.pop("obs_date"); self.assertEqual(self.run_all(raster(self.t / "b.tif"), m)["primary_class"], "UNUSABLE")

    def test_r3_to_r5_not_started_source_guard(self):
        for f in (ROOT / "src" / "flood_detection" / "ref_integration.py", ROOT / "scripts" / "reference_integration_check.py"):
            s = f.read_text(encoding="utf-8").replace("no recall/accuracy/false-positive claim", "")        # the one place the word appears is the disclaimer itself
            import re
            for bad in (r"import ee\b", r"agreement import", r"from sklearn", r"xgboost", r"\bshap\b", r"\.fit\(", r"\biou\b", r"\brecall\b", r"requests\.", r"urlopen", r"write_raster", r"rasterio\.warp", r"\breproject\("):
                self.assertIsNone(re.search(bad, s), f"{f.name}: {bad}")

def tree_hash(d): return {str(p.relative_to(d)): sha(p) for p in sorted(Path(d).rglob("*")) if p.is_file()}


class MainBase(Base):
    def setUp(self):
        super().setUp()
        from src.utils import paths as P, config as UC
        self.P, self.UC, self.SA = P, UC, SC.sa
        self.root = self.t / "proj"; cfg = self.root / "config"; cfg.mkdir(parents=True); proc = self.root / "data" / "processed"; proc.mkdir(parents=True)
        for n in ("s1_preprocess.json", "settings.json", "rainfall_events.json"): shutil.copy(ROOT / "config" / n, cfg / n)
        gpd.GeoDataFrame(geometry=[AOI], crs=4326).to_file(proc / "study_area_wgs84.geojson", driver="GeoJSON"); gpd.GeoDataFrame(geometry=[AOI], crs=4326).to_crs(32644).to_file(proc / "study_area_utm44n.geojson", driver="GeoJSON")
        (proc / "study_area_meta.json").write_text("{}"); self.ref_dir = self.root / "data" / "external" / "flood_labels"; self.ref_dir.mkdir(parents=True)
        self.ref = raster(self.ref_dir / "synthetic.tif"); self.mp = self.ref_dir / "synthetic.reference_meta.json"; self.mp.write_text(json.dumps(meta()))
        for d in ("outputs/chirps_2021/tables", "outputs/s1_2021_persistence/reports", "outputs/reports"): (self.root / d).mkdir(parents=True)
        (self.root / "outputs/chirps_2021/tables/x.csv").write_text("a,b\n1,2\n"); (self.root / "outputs/s1_2021_persistence/reports/m.json").write_text("{}"); (self.root / "outputs/reports/status.json").write_text('{"k": 1}')
        self.patches = [mock.patch.object(P, n, v) for n, v in (("ROOT", self.root), ("CONFIG", cfg), ("OUT_REP", self.root / "outputs/reports"), ("OUT_TAB", self.root / "outputs/tables"), ("OUT_FIG", self.root / "outputs/figures"), ("OUT_MAPS", self.root / "outputs/maps"))]
        self.patches += [mock.patch.object(UC, "CONFIG", cfg), mock.patch.object(SC.sa, "WGS", proc / "study_area_wgs84.geojson"), mock.patch.object(SC.sa, "UTM", proc / "study_area_utm44n.geojson"), mock.patch.object(SC.sa, "META", proc / "study_area_meta.json")]
        UC.load_settings.cache_clear(); [p.start() for p in self.patches]; self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)]); self.addCleanup(UC.load_settings.cache_clear)
        self.out = self.root / "outputs" / "flood_reference_readiness" / "synthetic"

    def go(self, *extra, ref=None, mp=None):
        with mock.patch("builtins.print"): return SC.main(["--reference", str(ref or self.ref), "--meta", str(mp or self.mp), "--today", str(TODAY), *extra])


class TestMain(MainBase):
    def test_end_to_end_additive_and_read_only(self):
        before = tree_hash(self.root); rc = self.go(); self.assertEqual(rc, 0); after = tree_hash(self.root)
        new = sorted(set(after) - set(before)); self.assertEqual(len(new), 7); self.assertTrue(all(n.replace("\\", "/").startswith("outputs/flood_reference_readiness/synthetic/") for n in new))
        self.assertEqual({k: v for k, v in before.items()}, {k: after[k] for k in before})                                  # every pre-existing file (reference, sidecar, CHIRPS, persistence, status.json, config, AOI) byte-identical
        man = json.loads((self.out / "reference_integration_manifest.json").read_text()); self.assertTrue(man["inputs_unchanged"]); self.assertFalse(man["status_json_modified"]); self.assertEqual(man["primary_class"], "CANDIDATE_LABEL_COMPARISON")
        rep = (self.out / "reference_integration_report.md").read_text(); self.assertIn("NOT flood-map accuracy validation", rep); self.assertIn("PROPOSED", rep); r2 = json.loads((self.out / "R2_readiness.json").read_text()); self.assertIn("NOT ASSESSED", r2["authoritative_reference"])
        self.assertEqual(len(pd.read_csv(self.out / "R1_temporal_offsets.csv")), 8)

    def test_no_overwrite_and_protected_directories(self):
        self.assertEqual(self.go(), 0); snap = tree_hash(self.out); self.assertEqual(self.go(), 2); self.assertEqual(tree_hash(self.out), snap)
        for bad in ("outputs", "outputs/reports", "outputs/chirps_2021", "outputs/chirps_2021/new", "outputs/s1_2021_persistence", "outputs/s1_2021_persistence/sub", "data/external/flood_labels", "data/external/flood_labels/out"):
            self.assertEqual(self.go("--outdir", str(self.root / bad)), 2, bad)
        self.assertFalse((self.root / "outputs/chirps_2021/new").exists())

    def test_hash_before_parse_ordering_in_main(self):
        ev = []; real_hash, real_loads, real_rf, real_lsa = RI.sha256_file, json.loads, gpd.read_file, SC.load_study_area
        h = lambda p: (ev.append(("hash", Path(p).name)), real_hash(p))[1]                                                # noqa: E731
        jl = lambda *a, **k: (ev.append(("json.loads", "")), real_loads(*a, **k))[1]                                       # noqa: E731
        rf = lambda p, *a, **k: (ev.append(("read_file", Path(p).name)), real_rf(p, *a, **k))[0 + 1]                       # noqa: E731
        ls = lambda: (ev.append(("load_study_area", "")), real_lsa())[1]                                                   # noqa: E731
        with mock.patch.object(RI, "sha256_file", h), mock.patch.object(json, "loads", jl), mock.patch.object(gpd, "read_file", rf), mock.patch.object(SC, "load_study_area", ls): self.assertEqual(self.go(), 0)
        first = lambda pred: next(i for i, e in enumerate(ev) if pred(e))                                                  # noqa: E731
        parse = min(first(lambda e: e[0] in ("json.loads", "read_file", "load_study_area")), len(ev))
        hashed = {e[1] for e in ev[:parse] if e[0] == "hash"}
        for n in ("synthetic.tif", "synthetic.reference_meta.json", "s1_preprocess.json", "study_area_wgs84.geojson", "study_area_utm44n.geojson", "settings.json", "study_area_meta.json", "rainfall_events.json"): self.assertIn(n, hashed, n)
        self.assertTrue(all(e[0] == "hash" for e in ev[:parse])); self.assertGreater(len([e for e in ev if e == ("hash", "synthetic.tif")]), 2)   # reference hashed in preflight, by intake (before/after) and after all outputs

    def test_missing_inputs_stop_before_anything_is_written(self):
        self.assertEqual(self.go(ref=self.ref_dir / "absent.tif"), 2); self.assertEqual(self.go(mp=self.ref_dir / "absent.json"), 2); self.assertFalse(self.out.exists())

    def test_malformed_sidecar_is_a_finding_not_a_crash(self):
        self.mp.write_text("{ nope"); self.assertEqual(self.go(), 0); man = json.loads((self.out / "reference_integration_manifest.json").read_text()); self.assertEqual(man["r0_status"], "FAIL"); self.assertEqual(man["primary_class"], "UNUSABLE")
        self.assertIn("META_PARSE", (self.out / "R0_intake_findings.csv").read_text())

    def test_2015_style_reference_reports_fail_alignment_and_qualitative_class(self):
        self.mp.write_text(json.dumps(meta(obs_date="2015-12-03"))); self.assertEqual(self.go("--event-window", "2015_dec", "2015-11-08", "2015-12-05"), 0)
        man = json.loads((self.out / "reference_integration_manifest.json").read_text()); self.assertEqual(man["r1_status"], "FAIL"); self.assertEqual(man["primary_class"], "QUALITATIVE_ONLY"); self.assertEqual(len(man["event_windows"]), 2)

    def test_template_is_all_unconfirmed(self):
        t = json.loads((ROOT / "docs" / "reference_meta_template.json").read_text())
        for k, v in t.items():
            if k != "_comment" and isinstance(v, str): self.assertIn("UNCONFIRMED", v, k)
        r = RI.intake(self.ref, {k: v for k, v in t.items() if k != "_comment"}, AOI, TODAY); self.assertEqual(r["status"], RI.FAIL)


class TestV11NonFinite(Base):
    def f32(self, name, fill, nodata=None, nan_cols=None, inf_cols=None, ninf_cols=None):
        a = np.full(GRID.shape, fill, "float32")
        if nan_cols is not None: a[:, nan_cols] = np.nan
        if inf_cols is not None: a[:, inf_cols] = np.inf
        if ninf_cols is not None: a[:, ninf_cols] = -np.inf
        return raster(self.t / name, a, nodata=nodata, dtype="float32"), a

    def test_valid_mask_rule(self):
        a = np.ma.masked_array(np.array([1, np.nan, np.inf, -np.inf, 255.0, 0.0]), mask=[0, 0, 0, 0, 1, 0]); self.assertEqual(RI.valid_mask(a).tolist(), [True, False, False, False, False, True])
        self.assertTrue(RI.valid_mask(np.ma.masked_array(np.array([0, 1, 7], "uint8"))).all())

    def test_r0_excludes_nan_and_infinity_with_and_without_nodata(self):
        for nd in (None, -9999.0, float("nan")):
            p, a = self.f32(f"x_{nd}.tif", 1.0, nd, nan_cols=slice(0, 3), inf_cols=slice(3, 5), ninf_cols=slice(5, 6)); finite = int(np.isfinite(a).sum())
            r = self.r0(p, class_meaning={"1": "flooded", "0": "not"}); self.assertEqual(r["info"]["valid_cells"], finite, nd)
            nan_masked = int(np.isnan(a).sum()) if (nd is not None and np.isnan(nd)) else 0                                      # NaN declared as NoData is masked (NoData), not counted as non-finite data
            self.assertEqual(r["info"]["nonfinite_cells"], a.size - finite - nan_masked, nd); self.assertEqual(self.lvl(r, "RASTER_NONFINITE"), RI.WARN); self.assertEqual(r["info"]["values"], [1.0])
            self.assertNotEqual(r["status"], RI.FAIL, [f for f in r["findings"] if f["level"] == RI.FAIL])
            if nd is None: self.assertEqual(self.lvl(r, "RASTER_NODATA"), RI.WARN)

    def test_all_nonfinite_raster_fails_even_without_nodata(self):
        for fill in (np.nan, np.inf, -np.inf):
            p, _ = self.f32(f"all_{fill}.tif", fill); r = self.r0(p); self.assertIn("RASTER_DATA", self.codes(r, RI.FAIL), fill); self.assertEqual(r["info"]["valid_cells"], 0)

    def test_clean_float_raster_has_no_nonfinite_finding(self):
        p, _ = self.f32("clean.tif", 1.0, -9999.0); r = self.r0(p); self.assertNotIn("RASTER_NONFINITE", self.codes(r)); self.assertEqual(r["info"]["nonfinite_cells"], 0)

    def test_r1_aoi_valid_share_uses_the_same_finite_rule(self):
        half = slice(0, GRID.width // 2)
        for nd in (None, -9999.0):
            p, a = self.f32(f"h_{nd}.tif", 1.0, nd, nan_cols=half); r0, r1 = align(self.t, p); sh = r1["raster_aoi"]["valid_share_of_aoi_cells"]
            with rasterio.open(p) as ds: inside = rasterio.features.geometry_mask([gpd.GeoSeries([AOI], crs=4326).to_crs(ds.crs).iloc[0]], out_shape=a.shape, transform=ds.transform, invert=True)
            expect = float((inside & np.isfinite(a)).sum() / inside.sum()); self.assertAlmostEqual(sh, expect, places=9); self.assertLess(sh, 0.9); self.assertEqual(self.lvl(r1, "AOI_VALID_COVERAGE"), RI.WARN)
            self.assertEqual(r0["info"]["valid_cells"], int(np.isfinite(a).sum()))                                                  # R0 and R1 agree on what "valid" means
        p, a = self.f32("inf.tif", 1.0, None, inf_cols=slice(0, GRID.width)); _, r1 = align(self.t, p); self.assertEqual(r1["raster_aoi"]["valid_share_of_aoi_cells"], 0.0); self.assertEqual(self.lvl(r1, "AOI_VALID_COVERAGE"), RI.FAIL)
        p, a = self.f32("minf.tif", 1.0, None, ninf_cols=half); self.assertLess(align(self.t, p)[1]["raster_aoi"]["valid_share_of_aoi_cells"], 0.9)

    def test_nonfinite_blocks_candidate_readiness_through_valid_share(self):
        half = slice(0, GRID.width // 2); p, _ = self.f32("h.tif", 1.0, None, nan_cols=half); mm = meta(); r0 = RI.intake(p, mm, AOI, TODAY); r1 = RI.alignment(p, r0, AOI, GRID, DATES); r2 = RI.readiness(mm, r0, r1)
        self.assertTrue(any("valid reference data" in b for b in r2["candidate_label_comparison"]["blockers"])); self.assertNotEqual(r2["primary_class"], "CANDIDATE_LABEL_COMPARISON")


class TestV11Shapefile(Base):
    def shp(self, name="ref.shp", **kw): return poly_file(self.t / name, [AOI.buffer(0.01)])

    def test_all_companion_files_are_part_of_the_dataset(self):
        p = self.shp(); (self.t / "ref.shp.xml").write_text("<x/>"); (self.t / "ref.reference_meta.json").write_text("{}"); (self.t / "ref_other.dbf").write_bytes(b"x"); (self.t / "other.shx").write_bytes(b"x")
        names = sorted(c.name for c in RI.dataset_files(p)); self.assertEqual(names, ["ref.cpg", "ref.dbf", "ref.prj", "ref.shp", "ref.shp.xml", "ref.shx"]); self.assertNotIn("ref.reference_meta.json", names); self.assertNotIn("ref_other.dbf", names)
        (self.t / "REF.DBF.bak").write_bytes(b"x"); self.assertNotIn("REF.DBF.bak", [c.name for c in RI.dataset_files(p)])

    def test_intake_hashes_every_file_and_passes_when_unchanged(self):
        p = self.shp(); before = {c.name: sha(c) for c in RI.dataset_files(p)}; r = self.r0(p, kind="extent_polygons"); self.assertTrue(r["unchanged"]); self.assertEqual(r["dataset_sha256_before"], before); self.assertEqual(r["dataset_sha256_after"], before)
        self.assertEqual(r["dataset_files"], sorted(before)); self.assertEqual(self.lvl(r, "SHAPEFILE_PARTS"), RI.PASS); self.assertEqual(r["status"], RI.PASS, [f for f in r["findings"] if f["level"] != RI.PASS]); self.assertEqual({c.name: sha(c) for c in RI.dataset_files(p)}, before)

    def test_modifying_any_companion_during_intake_is_detected(self):
        real = gpd.read_file
        for comp in (".dbf", ".shx", ".prj", ".cpg", ".shp"):
            p = self.shp(f"m{comp[1:]}.shp"); target = p.with_suffix(comp)
            def rf(path, *a, **k):
                out = real(path, *a, **k)
                with open(target, "ab") as f: f.write(b"\x00tamper")
                return out
            with mock.patch.object(gpd, "read_file", rf): r = self.r0(p, kind="extent_polygons")
            self.assertFalse(r["unchanged"], comp); f = next(x for x in r["findings"] if x["code"] == "INTEGRITY"); self.assertEqual(f["level"], RI.FAIL); self.assertEqual(f["evidence"]["changed"], [target.name]); self.assertEqual(r["status"], RI.FAIL)

    def test_incomplete_shapefile_is_a_failure(self):
        p = self.shp(); p.with_suffix(".dbf").unlink(); r = self.r0(p, kind="extent_polygons"); self.assertEqual(self.lvl(r, "SHAPEFILE_PARTS"), RI.FAIL); self.assertEqual(r["status"], RI.FAIL)

    def test_geotiff_sidecars_are_included(self):
        p = raster(self.t / "a.tif"); (self.t / "a.tif.aux.xml").write_text("<x/>"); (self.t / "a.tif.ovr").write_bytes(b"o"); self.assertEqual(sorted(c.name for c in RI.dataset_files(p)), ["a.tif", "a.tif.aux.xml", "a.tif.ovr"])
        self.assertEqual(sorted(self.r0(p)["dataset_files"]), ["a.tif", "a.tif.aux.xml", "a.tif.ovr"])


class TestV11Dates(Base):
    def test_strict_parser_accepts_only_documented_iso_dates(self):
        for ok in ("2021-11-05", "2020-02-29", "2015-12-03", date(2021, 11, 5)): self.assertEqual(RI.parse_iso_date(ok), ok if isinstance(ok, date) else date.fromisoformat(ok), ok)
        for bad in ("2021-11-05garbage", "2021-11-05T06:00:00Z", "2021-11-05 06:00", " 2021-11-05", "2021-11-05 ", "2021-11-05\n", "20211105", "2021-1-5", "2021-11-5", "2021/11/05", "05-11-2021", "2021-02-30", "2021-13-01", "2021-00-10",
                    "2019-02-29", "\u0662\u0660\u0662\u0661-\u0661\u0661-\u0660\u0665", "", "garbage", 20211105, 5.0, None, True, pd.Timestamp("2021-11-05").to_pydatetime()): self.assertIsNone(RI.parse_iso_date(bad), repr(bad))

    def test_intake_rejects_malformed_dates(self):
        p = raster(self.t / "a.tif")
        for kw in (dict(obs_date="2021-11-05garbage"), dict(obs_date="2021-11-05T06:00:00Z"), dict(obs_date="20211105"), dict(obs_date_start="2021-11-01", obs_date_end="2021-11-05garbage"), dict(obs_date_start="2021-11-01garbage", obs_date_end="2021-11-05")):
            m = meta(**kw)
            if "obs_date_start" in kw: m.pop("obs_date")
            r = RI.intake(p, m, AOI, TODAY); self.assertEqual(self.lvl(r, "DATE"), RI.FAIL, kw); self.assertIsNone(r["obs_range"], kw)
        r = self.r0(p, obs_date="2021-11-05"); self.assertEqual(self.lvl(r, "DATE"), RI.PASS); self.assertEqual(r["obs_range"], ["2021-11-05", "2021-11-05"])
        m = meta(obs_date_start="2021-11-01", obs_date_end="2021-11-05"); m.pop("obs_date"); self.assertEqual(self.lvl(RI.intake(p, m, AOI, TODAY), "DATE"), RI.PASS)

    def test_malformed_date_cannot_reach_readiness_as_usable(self):
        r = TestR2.run_all(self, raster(self.t / "a.tif"), obs_date="2021-11-05garbage"); self.assertEqual(r["primary_class"], "UNUSABLE")

    def test_library_temporal_rejects_bad_scene_or_window_dates(self):
        ok = ["2021-11-05", "2021-11-05"]
        for args in ((ok, ["2021-11-04x"], ()), (ok, ["2021-11-04"], [("w", "2021-9-1", "2021-11-28")]), (["2021-11-05x", "2021-11-05"], ["2021-11-04"], ())):
            with self.assertRaises(ValueError): RI.temporal(*args)


class TestV11AlignmentPolicy(Base):
    def r2(self, path, strict=False, **kw):
        mm = meta(**kw); r0 = RI.intake(path, mm, AOI, TODAY); r1 = RI.alignment(path, r0, AOI, GRID, DATES); return RI.readiness(mm, r0, r1, strict_alignment=strict)

    def mism(self, name):
        if name == "res10": return raster(self.t / "r10.tif", np.ones((GRID.height * 3, GRID.width * 3), "uint8"), transform=from_origin(GRID.transform.c, GRID.transform.f, 10, 10))
        if name == "crs": return raster(self.t / "wgs.tif", np.ones((200, 200), "uint8"), crs="EPSG:4326", transform=from_origin(80.17, 13.02, 0.0002, 0.0002))
        if name == "origin": return raster(self.t / "off.tif", transform=from_origin(GRID.transform.c + 7, GRID.transform.f, 30, 30))
        from affine import Affine
        return raster(self.t / "rot.tif", transform=Affine(30, 2, GRID.transform.c, 0, -30, GRID.transform.f))

    def test_thresholds_are_unchanged(self):
        self.assertEqual(RI.DEFAULTS, {"close_days": 3, "max_days": 6, "min_coverage_candidate": 0.95, "full_coverage": 0.999, "max_obs_range_days": 14})

    def test_aligned_raster_has_no_conditions_and_unchanged_verdict(self):
        r = self.r2(raster(self.t / "a.tif")); c = r["candidate_label_comparison"]; self.assertEqual(c["alignment_conditions"], []); self.assertEqual(c["team_decision_required"], []); self.assertNotIn("EXPLICIT TEAM DECISION", c["verdict"]); self.assertEqual(r["primary_class"], "CANDIDATE_LABEL_COMPARISON")

    def test_default_policy_requires_explicit_team_decision_without_changing_thresholds(self):
        for name, code in (("res10", "GRID_RES"), ("crs", "GRID_CRS"), ("origin", "GRID_ORIGIN"), ("rot", "RASTER_ROTATED")):
            r = self.r2(self.mism(name)); c = r["candidate_label_comparison"]
            self.assertTrue(any(x.startswith(code) for x in c["alignment_conditions"]), (name, c["alignment_conditions"])); self.assertEqual(c["blockers"], [], name)                                 # thresholds untouched: not a blocker by default
            self.assertIn("EXPLICIT TEAM DECISION ON ALIGNMENT", c["verdict"]); self.assertEqual(c["team_decision_required"], ["alignment"]); self.assertEqual(r["primary_class"], "CANDIDATE_LABEL_COMPARISON"); self.assertFalse(r["strict_alignment"])
            self.assertIn("ALIGNMENT POLICY", r["alignment_policy"]); self.assertIn("NOT ASSESSED", r["authoritative_reference"])

    def test_strict_policy_turns_each_condition_into_a_blocker(self):
        for name in ("res10", "crs", "origin", "rot"):
            r = self.r2(self.mism(name), strict=True); c = r["candidate_label_comparison"]; self.assertTrue(any("alignment mismatch (strict policy)" in b for b in c["blockers"]), name); self.assertTrue(c["verdict"].startswith("NOT READY")); self.assertNotEqual(r["primary_class"], "CANDIDATE_LABEL_COMPARISON"); self.assertEqual(c["team_decision_required"], [])
        r = self.r2(raster(self.t / "a.tif"), strict=True); self.assertEqual(r["primary_class"], "CANDIDATE_LABEL_COMPARISON")                    # strict has no effect on an aligned raster

    def test_conditions_do_not_hide_real_blockers(self):
        r = self.r2(self.mism("res10"), independent_of_s1=False); c = r["candidate_label_comparison"]; self.assertTrue(c["blockers"]); self.assertEqual(c["team_decision_required"], []); self.assertTrue(c["verdict"].startswith("NOT READY"))

    def test_vector_crs_difference_is_not_an_alignment_condition(self):
        r = self.r2(poly_file(self.t / "p.gpkg", [AOI.buffer(0.01)]), kind="extent_polygons"); c = r["candidate_label_comparison"]; self.assertEqual(c["alignment_conditions"], []); self.assertEqual(r["primary_class"], "CANDIDATE_LABEL_COMPARISON")

    def test_presence_only_and_qualitative_verdicts_unaffected_by_policy(self):
        a, b = self.r2(self.mism("res10")), self.r2(self.mism("res10"), strict=True)
        self.assertEqual(a["presence_only_comparison"], b["presence_only_comparison"]); self.assertEqual(a["qualitative_comparison"], b["qualitative_comparison"])


class TestV11Main(MainBase):
    def shp_ref(self):
        p = poly_file(self.ref_dir / "area.shp", [AOI.buffer(0.01)]); self.mp.write_text(json.dumps(meta(kind="extent_polygons"))); return p

    def test_cli_hashes_all_shapefile_files_and_leaves_them_unchanged(self):
        p = self.shp_ref(); before = tree_hash(self.root); self.assertEqual(self.go(ref=p), 0); after = tree_hash(self.root); self.assertEqual(before, {k: after[k] for k in before})
        man = json.loads((self.root / "outputs" / "flood_reference_readiness" / "area" / "reference_integration_manifest.json").read_text()); self.assertTrue(man["inputs_unchanged"])
        for ext in ("shp", "shx", "dbf", "prj", "cpg"): self.assertTrue(any(k.endswith(f"area.{ext}") for k in man["inputs_sha256_before"]), ext); self.assertTrue(any(k.endswith(f"area.{ext}") for k in man["inputs_sha256_after_all_outputs"]), ext)
        self.assertEqual(sorted(man["reference_dataset_files"]), ["area.cpg", "area.dbf", "area.prj", "area.shp", "area.shx"])

    def test_cli_detects_a_companion_file_changing_during_the_run(self):
        p = self.shp_ref(); real = gpd.read_file; dbf = p.with_suffix(".dbf")
        def rf(path, *a, **k):
            out = real(path, *a, **k)
            if str(path).endswith("area.shp"):
                with open(dbf, "ab") as f: f.write(b"\x00tamper")
            return out
        with mock.patch.object(gpd, "read_file", rf): rc = self.go(ref=p)
        self.assertEqual(rc, 3); man = json.loads((self.root / "outputs" / "flood_reference_readiness" / "area" / "reference_integration_manifest.json").read_text()); self.assertFalse(man["inputs_unchanged"])
        self.assertIn("INTEGRITY", (self.root / "outputs" / "flood_reference_readiness" / "area" / "R0_intake_findings.csv").read_text())

    def test_cli_detects_a_companion_changing_after_intake_before_the_final_check(self):
        p = self.shp_ref(); real = SC.RI.alignment; dbf = p.with_suffix(".dbf")
        def al(*a, **k):
            with open(dbf, "ab") as f: f.write(b"\x00late")
            return real(*a, **k)
        with mock.patch.object(SC.RI, "alignment", al): self.assertEqual(self.go(ref=p), 3)

    def test_cli_missing_companion_is_reported(self):
        p = self.shp_ref(); p.with_suffix(".dbf").unlink(); self.assertEqual(self.go(ref=p), 0); self.assertIn("SHAPEFILE_PARTS", (self.root / "outputs" / "flood_reference_readiness" / "area" / "R0_intake_findings.csv").read_text())

    def test_cli_rejects_malformed_dates_before_writing(self):
        for extra in (["--event-window", "w", "2021-9-1", "2021-11-28"], ["--event-window", "w", "2021-09-01", "2021-11-28garbage"], ["--today", "2026-11-26garbage"]):
            self.assertEqual(self.go(*extra), 2, extra); self.assertFalse(self.out.exists())
        self.assertEqual(self.go("--event-window", "ok", "2021-09-01", "2021-11-28"), 0)

    def test_cli_malformed_obs_date_in_sidecar_is_a_finding(self):
        self.mp.write_text(json.dumps(meta(obs_date="2021-11-05garbage"))); self.assertEqual(self.go(), 0)
        man = json.loads((self.out / "reference_integration_manifest.json").read_text()); self.assertEqual(man["r0_status"], "FAIL"); self.assertEqual(man["primary_class"], "UNUSABLE")

    def test_cli_alignment_policy_default_vs_strict(self):
        p = raster(self.ref_dir / "res10.tif", np.ones((GRID.height * 3, GRID.width * 3), "uint8"), transform=from_origin(GRID.transform.c, GRID.transform.f, 10, 10)); self.mp.write_text(json.dumps(meta()))
        self.assertEqual(self.go(ref=p), 0); od = self.root / "outputs" / "flood_reference_readiness" / "res10"; man = json.loads((od / "reference_integration_manifest.json").read_text()); r2 = json.loads((od / "R2_readiness.json").read_text())
        self.assertEqual(man["primary_class"], "CANDIDATE_LABEL_COMPARISON"); self.assertEqual(r2["candidate_label_comparison"]["team_decision_required"], ["alignment"]); self.assertIn("TEAM DECISION REQUIRED: alignment", (od / "reference_integration_report.md").read_text()); self.assertFalse(man["strict_alignment"])
        self.assertEqual(self.go("--strict-alignment", "--outdir", str(self.root / "outputs" / "flood_reference_readiness" / "res10_strict"), ref=p), 0)
        od2 = self.root / "outputs" / "flood_reference_readiness" / "res10_strict"; man2 = json.loads((od2 / "reference_integration_manifest.json").read_text()); self.assertNotEqual(man2["primary_class"], "CANDIDATE_LABEL_COMPARISON"); self.assertTrue(man2["strict_alignment"])


class TestV12PersistenceNamespace(MainBase):
    def test_any_persistence_prefixed_output_dir_is_rejected_existing_or_not(self):
        (self.root / "outputs" / "s1_2021_persistence_backup" / "tables").mkdir(parents=True); (self.root / "outputs" / "s1_2021_persistence_backup" / "tables" / "t.csv").write_text("a\n1\n")      # an EXISTING backup dir
        snap = tree_hash(self.root)
        for bad in ("outputs/s1_2021_persistence_v1_3", "outputs/s1_2021_persistence_v1_3/sub", "outputs/s1_2021_persistence_backup", "outputs/s1_2021_persistence_backup/new", "outputs/s1_2021_persistence_v1_2",
                    "outputs/s1_2021_persistence_v1_2/reports", "outputs/s1_2021_persistence", "outputs/s1_2021_persistence_anything_else", "outputs/S1_2021_PERSISTENCE_V9"):
            self.assertEqual(self.go("--outdir", str(self.root / bad)), 2, bad)
        self.assertEqual(tree_hash(self.root), snap)                                                                    # nothing created or changed, including the non-existent v1_3 / v1_2 names
        self.assertFalse((self.root / "outputs" / "s1_2021_persistence_v1_3").exists())

    def test_messages_name_the_reason(self):
        out = []
        with mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a)))): rc = SC.main(["--reference", str(self.ref), "--meta", str(self.mp), "--outdir", str(self.root / "outputs" / "s1_2021_persistence_v1_3"), "--today", str(TODAY)])
        self.assertEqual(rc, 2); self.assertTrue(any("reserved outputs/s1_2021_persistence*" in x for x in out), out)

    def test_existing_protections_and_normal_default_still_work(self):
        for bad in ("outputs", "outputs/reports", "outputs/tables", "outputs/figures", "outputs/maps", "outputs/chirps_2021", "outputs/chirps_2021/new", "data/external/flood_labels", "data/external/flood_labels/out"): self.assertEqual(self.go("--outdir", str(self.root / bad)), 2, bad)
        self.assertEqual(self.go("--outdir", str(self.root / "outputs" / "flood_reference_readiness" / "other_s1_2021_persistence")), 0)       # the prefix only reserves TOP-LEVEL outputs/s1_2021_persistence*
        self.assertEqual(self.go(), 0)

    def test_helper_functions(self):
        r = self.root; self.assertTrue(SC.persistence_reserved(r / "outputs" / "s1_2021_persistence_x" / "a", r)); self.assertFalse(SC.persistence_reserved(r / "outputs" / "flood_reference_readiness" / "s1_2021_persistence", r)); self.assertFalse(SC.persistence_reserved(r.parent / "elsewhere", r))
        (r / "outputs" / "s1_2021_persistence_backup").mkdir(); names = {d.name for d in SC.protected_dirs(r, self.ref)}; self.assertTrue({"s1_2021_persistence", "s1_2021_persistence_v1_2", "s1_2021_persistence_backup", "chirps_2021", "reports", "tables", "figures", "maps", "flood_labels"} <= names)


if __name__ == "__main__": unittest.main()
