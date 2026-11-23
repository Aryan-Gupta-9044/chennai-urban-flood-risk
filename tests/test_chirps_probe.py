"""CHIRPS v3 probe helper tests on SYNTHETIC arrays/geometry. The Earth Engine calls of scripts/probe_chirps_coverage.py are NOT covered (UNTESTED live)."""
import json
import sys
import unittest
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from rasterio.transform import Affine
from shapely.geometry import Polygon, box
from src.geospatial import chirps

TR = Affine(0.05, 0, -180.0, 0, -0.05, 50.0)          # shape of the CHIRPS grid as described (0.05 deg, north-up); values here are synthetic


class T(unittest.TestCase):
    def test_grid_from_projection(self):
        crs, tr = chirps.grid_from_ee_projection({"type": "Projection", "crs": "EPSG:4326", "transform": [0.05, 0, -180, 0, -0.05, 50]})
        self.assertEqual((crs, tr.a, tr.e), ("EPSG:4326", 0.05, -0.05))
        for bad in ({"crs": "EPSG:4326", "transform": [0.05, 0.01, 0, 0, -0.05, 0]}, {"crs": "EPSG:4326", "transform": [0.05, 0, 0, 0, 0.05, 0]}, {}, None):
            with self.assertRaises(ValueError): chirps.grid_from_ee_projection(bad)

    def test_window_is_grid_aligned_and_covers_bounds(self):
        b = (80.134, 12.852, 80.333, 13.235)
        win = chirps.snap_window(TR, b, 1); wtr = chirps.window_transform(TR, win); wb = chirps.window_bounds(TR, win)
        self.assertTrue(wb[0] < b[0] and wb[1] < b[1] and wb[2] > b[2] and wb[3] > b[3])
        self.assertAlmostEqual((wtr.c - TR.c) / TR.a, round((wtr.c - TR.c) / TR.a)); self.assertAlmostEqual((wtr.f - TR.f) / TR.e, round((wtr.f - TR.f) / TR.e))
        self.assertEqual((wtr.a, wtr.e), (TR.a, TR.e))                        # native pixel size preserved

    def _setup(self, aoi):
        win = chirps.snap_window(TR, aoi.bounds, 1); wtr = chirps.window_transform(TR, win)
        w, touch = chirps.aoi_cell_weights(wtr, (win[3], win[2]), aoi); return win, wtr, w, touch

    def test_weights_use_polygon_not_bbox(self):
        tri = Polygon([(80.10, 12.85), (80.35, 12.85), (80.10, 13.25)])           # triangle: half of its bbox is empty
        win, wtr, w, touch = self._setup(tri)
        self.assertAlmostEqual(float(w.sum()), 1.0, places=9)
        bbox_cells = int(np.ceil((tri.bounds[2] - tri.bounds[0]) / .05) + 1) * int(np.ceil((tri.bounds[3] - tri.bounds[1]) / .05) + 1)
        self.assertLess(int(touch.sum()), bbox_cells)                              # fewer cells touch the polygon than its bbox implies
        # a cell wholly in the empty bbox corner must have zero weight
        r, c = np.unravel_index(np.argmin(np.where(touch, 9, np.arange(w.size).reshape(w.shape))), w.shape)
        self.assertEqual(w[r, c], 0.0)

    def test_coverage_partial_and_full(self):
        aoi = box(80.101, 12.851, 80.249, 13.049)                                  # ~ 3x4 cells
        win, wtr, w, touch = self._setup(aoi)
        full = chirps.coverage(np.ones_like(touch), w); self.assertAlmostEqual(full["aoi_area_coverage"], 1.0, places=9); self.assertEqual(full["cells_missing"], 0)
        v = np.ones_like(touch); rr, cc = np.where(touch); v[rr[0], cc[0]] = False                       # one masked cell
        part = chirps.coverage(v, w); self.assertLess(part["aoi_area_coverage"], 1.0); self.assertEqual(part["cells_missing"], 1)
        self.assertAlmostEqual(part["aoi_area_coverage"], 1.0 - w[rr[0], cc[0]], places=9)
        none = chirps.coverage(np.zeros_like(touch), w); self.assertEqual(none["aoi_area_coverage"], 0.0); self.assertEqual(none["cells_valid"], 0)

    def test_cells_outside_aoi_do_not_count(self):
        aoi = box(80.101, 12.851, 80.149, 12.899); win, wtr, w, touch = self._setup(aoi)
        v = np.zeros_like(touch); v[~touch] = True                                   # everything valid EXCEPT AOI cells
        self.assertEqual(chirps.coverage(v, w)["aoi_area_coverage"], 0.0)

    def test_export_consistency(self):
        p = np.array([[1.0, 0.0], [-9999.0, 5.0]]); v = np.array([[1, 1], [0, 1]])
        self.assertEqual(chirps.check_export(p, v), [])                                # genuine 0 mm in a valid cell is fine
        self.assertTrue(chirps.check_export(np.array([[1.0, 0.0], [0.0, 5.0]]), v))    # masked cell zero-filled -> flagged
        self.assertTrue(chirps.check_export(np.array([[1.0, -9999.0], [-9999.0, 5.0]]), v))   # valid cell holds sentinel -> flagged
        self.assertTrue(chirps.check_export(np.array([[np.nan, 0.0], [-9999.0, 5.0]]), v))
        self.assertTrue(chirps.check_export(np.array([[-3.0, 0.0], [-9999.0, 5.0]]), v))       # negative rainfall flagged
        self.assertTrue(chirps.check_export(p, np.array([[1, 2], [0, 1]])))
        self.assertTrue(chirps.check_export(p, np.ones((3, 3))))

    def test_date_continuity(self):
        exp = [date(2015, 7, 21) + __import__("datetime").timedelta(days=i) for i in range(153)]; self.assertEqual(exp[-1], date(2015, 12, 20))
        ok = chirps.continuity(exp, exp); self.assertEqual((ok["missing"], ok["duplicated"], ok["unexpected"]), ([], [], []))
        got = [d for d in exp if d != date(2015, 9, 1)] + [exp[5], date(2016, 1, 1)]
        c = chirps.continuity(got, exp); self.assertEqual(c["missing"], [date(2015, 9, 1)]); self.assertEqual(c["duplicated"], [exp[5]]); self.assertEqual(c["unexpected"], [date(2016, 1, 1)])

    def test_temporal_completeness_not_hidden_by_area_threshold(self):
        exp = [f"d{i}" for i in range(10)]
        cov = {d: 1.0 for d in exp}; cov["d3"] = 0.94; cov["d4"] = 0.0; del cov["d5"]                 # one low, one empty, one absent
        t = chirps.temporal_completeness(cov, exp, 0.95)
        self.assertEqual(t["dates_meeting"], 7); self.assertAlmostEqual(t["percent"], 70.0); self.assertEqual(t["failing"], ["d3", "d4", "d5"])

    def test_verdict_stops_and_never_lowers_threshold(self):
        cont = {"missing": [], "duplicated": [], "unexpected": []}
        comp = {"dates_meeting": 153, "dates_expected": 153, "percent": 100.0}
        self.assertEqual(chirps.verdict(0.95, {"2015-12-01": 0.97}, comp, cont, [])[0], "PROCEED-TO-REVIEW")
        v, why = chirps.verdict(0.95, {"2015-12-01": 0.31}, comp, cont, []); self.assertEqual(v, "STOP"); self.assertIn("31.0%", " ".join(why))
        self.assertEqual(chirps.verdict(0.95, {"a": 1.0}, {"dates_meeting": 150, "dates_expected": 153, "percent": 98.0}, cont, [])[0], "STOP")
        self.assertEqual(chirps.verdict(0.95, {"a": 1.0}, comp, {"missing": [date(2015, 8, 1)], "duplicated": [], "unexpected": []}, [])[0], "STOP")
        self.assertEqual(chirps.verdict(0.95, {"a": 1.0}, comp, cont, ["bad export"])[0], "STOP")
        self.assertEqual(chirps.verdict(0.95, {}, comp, cont, [])[0], "STOP")

    def test_metadata_constants(self):
        self.assertEqual(chirps.DATASET_ID, "UCSB-CHC/CHIRPS/V3/DAILY_SAT")
        self.assertIn("NOT verified local", chirps.DAY_DEFINITION); self.assertNotIn("UTC calendar day", chirps.DAY_DEFINITION)
        self.assertIn("CC BY 4.0", chirps.LICENCE_NOTE); self.assertIn("public domain", chirps.LICENCE_NOTE)
        self.assertIn("not independent", chirps.INDEPENDENCE_NOTE)


class RecordingEE:
    """Fake `ee` that records constructor calls and REJECTS arguments the real API does not take (Point has no geodesic)."""
    def __init__(self):
        self.calls = []
        outer = self
        class Geometry:
            def __init__(self, geo_json=None, proj=None, geodesic=None, evenOdd=None): outer.calls.append(("Geometry", dict(geo_json=geo_json, proj=proj, geodesic=geodesic)))
            @staticmethod
            def Point(coords=None, proj=None): outer.calls.append(("Point", dict(coords=coords, proj=proj)))
            @staticmethod
            def Rectangle(coords=None, proj=None, geodesic=None, evenOdd=None): outer.calls.append(("Rectangle", dict(coords=coords, proj=proj, geodesic=geodesic)))
            @staticmethod
            def MultiPolygon(coords=None, proj=None, geodesic=None, maxError=None, evenOdd=None): outer.calls.append(("MultiPolygon", dict(coords=coords, proj=proj, geodesic=geodesic)))
        self.Geometry = Geometry


class TestEEGeometryConstruction(unittest.TestCase):
    """Regression for the live failure `Unrecognized arguments {'geodesic'} to GeometryConstructors.Point` (probe v1 passed geodesic positionally)."""
    def test_builders_use_supported_arguments_and_preserve_crs_and_centres(self):
        ee = RecordingEE()
        chirps.ee_point(ee, 80.225, 13.025, "EPSG:4326")
        chirps.ee_rectangle(ee, (80.0, 12.8, 80.4, 13.3), "EPSG:4326")
        chirps.ee_multipolygon_from_rects(ee, [(80.0, 12.8, 80.05, 12.85)], "EPSG:4326")
        chirps.ee_geometry_from_geojson(ee, {"type": "Polygon", "coordinates": []}, "EPSG:4326")
        d = {n: kw for n, kw in ee.calls}
        self.assertEqual(set(d["Point"]), {"coords", "proj"})                      # NO geodesic for Point
        self.assertEqual(d["Point"]["coords"], [80.225, 13.025]); self.assertEqual(d["Point"]["proj"], "EPSG:4326")
        for k in ("Rectangle", "MultiPolygon", "Geometry"):
            self.assertEqual(d[k]["proj"], "EPSG:4326"); self.assertIs(d[k]["geodesic"], False)      # planar, in the grid CRS
        self.assertEqual(d["MultiPolygon"]["coords"], [[[[80.0, 12.8], [80.05, 12.8], [80.05, 12.85], [80.0, 12.85], [80.0, 12.8]]]])

    def test_probe_script_builds_all_geometry_through_helpers(self):
        src = (ROOT / "scripts" / "probe_chirps_coverage.py").read_text(encoding="utf-8")
        self.assertNotIn("ee.Geometry", src)                                         # no direct constructor calls with positional extras
        for h in ("ee_point", "ee_multipolygon_from_rects", "ee_geometry_from_geojson"):
            self.assertIn(f"chirps.{h}(", src)

    def test_against_installed_earth_engine_signatures(self):
        try:
            import ee, inspect
        except ImportError:
            self.skipTest("earthengine-api not installed")
        sig = inspect.signature(ee.Geometry.Point).parameters
        self.assertNotIn("geodesic", sig)                                            # documents why the old call failed
        ok_point = {"coords", "proj"}
        self.assertTrue(ok_point <= set(sig))
        for name, kws in (("Rectangle", {"coords", "proj", "geodesic"}), ("MultiPolygon", {"coords", "proj", "geodesic"})):
            self.assertTrue(kws <= set(inspect.signature(getattr(ee.Geometry, name)).parameters), name)
        self.assertTrue({"geo_json", "proj", "geodesic"} <= set(inspect.signature(ee.Geometry.__init__).parameters))
        # the builders only ever pass keywords that exist in the installed signatures
        rec = RecordingEE(); chirps.ee_point(rec, 1, 2, "EPSG:4326"); self.assertTrue(set(rec.calls[0][1]) <= set(sig))


class TestExportRequestAndValidation(unittest.TestCase):
    """Regression for the live failure: exports came back 1.0 deg pixels, shape [2,1] because the request used `crsTransform` + `region`
    (ignored by Earth Engine) instead of documented `crs_transform` + `dimensions`."""
    def _win(self):
        win = chirps.snap_window(TR, (80.134, 12.852, 80.333, 13.235), 1); return win, chirps.window_transform(TR, win), (win[3], win[2])

    def test_download_params_use_documented_keys_and_window_origin(self):
        win, wtr, shape = self._win()
        p = chirps.download_params("EPSG:4326", wtr, shape)
        self.assertEqual(set(p), {"crs", "crs_transform", "dimensions", "format"})
        self.assertNotIn("crsTransform", p); self.assertNotIn("region", p); self.assertNotIn("scale", p)
        self.assertEqual(p["crs_transform"], [0.05, 0.0, wtr.c, 0.0, -0.05, wtr.f])            # WINDOW origin, not the global (-180, 50) origin
        self.assertEqual(p["dimensions"], [shape[1], shape[0]])                                 # [width, height]
        self.assertEqual(p["format"], "GEO_TIFF")

    def test_download_param_names_exist_in_installed_ee_docs(self):
        try:
            import ee
        except ImportError:
            self.skipTest("earthengine-api not installed")
        doc = ee.Image.getDownloadURL.__doc__
        win, wtr, shape = self._win()
        for k in chirps.download_params("EPSG:4326", wtr, shape):
            self.assertIn(f"- {k}:", doc, f"{k} is not a documented getDownloadURL parameter")
        self.assertIn("ignored if crs", doc)                                                      # region/scale are ignored beside crs+crs_transform

    def test_script_requests_through_helper_only(self):
        src = (ROOT / "scripts" / "probe_chirps_coverage.py").read_text(encoding="utf-8")
        self.assertIn("chirps.download_params(", src); self.assertNotIn('"crsTransform": list(tr)', src); self.assertNotIn('"region": region', src)

    def test_grid_validation_catches_the_live_failure_and_accepts_correct_export(self):
        win, wtr, shape = self._win()
        bad = chirps.check_export_grid(Affine(1.0, 0, 80.013, 0, -1.0, 13.97), (2, 1), "EPSG:4326", wtr, shape, TR, "EPSG:4326")
        txt = " | ".join(bad); self.assertIn("pixel size", txt); self.assertIn("shape [2, 1]", txt); self.assertIn("not aligned", txt)
        self.assertEqual(chirps.check_export_grid(wtr, shape, "EPSG:4326", wtr, shape, TR, "EPSG:4326"), [])
        half = Affine(0.05, 0, wtr.c + 0.025, 0, -0.05, wtr.f)                                    # shifted by half a cell: not on the native lattice
        self.assertTrue(any("not aligned" in x for x in chirps.check_export_grid(half, shape, "EPSG:4326", wtr, shape, TR, "EPSG:4326")))
        self.assertTrue(any("CRS" in x for x in chirps.check_export_grid(wtr, shape, "EPSG:3857", wtr, shape, TR, "EPSG:4326")))
        shifted = Affine(0.05, 0, wtr.c + 0.05, 0, -0.05, wtr.f)                                  # aligned but the wrong window
        self.assertTrue(any("origin" in x for x in chirps.check_export_grid(shifted, shape, "EPSG:4326", wtr, shape, TR, "EPSG:4326")))

    def test_server_row_sanity_rejects_impossible_coverage_and_wrong_geometry(self):
        w = [0.1] * 10
        self.assertEqual(chirps.server_row_problems(10, 10, 10, 1.0, w), [])
        self.assertEqual(chirps.server_row_problems(10, 10, 4, 0.4, w), [])
        self.assertTrue(chirps.server_row_problems(10, 10, 4, 1.0, w))                           # 100 % with 6 masked cells is impossible
        self.assertTrue(chirps.server_row_problems(10, 6, 6, 0.6, w))                            # geometry selected the wrong number of pixels
        self.assertTrue(chirps.server_row_problems(10, 10, None, 1.0, w))
        self.assertTrue(chirps.server_row_problems(10, 10, 11, 1.0, w))

    def test_server_vs_local_comparison(self):
        self.assertEqual(chirps.compare_server_local(0.97, 28, 0.965, 28), [])
        self.assertTrue(chirps.compare_server_local(1.0, 29, 0.4, 12))
        self.assertTrue(chirps.compare_server_local(None, None, 0.4, 12))

    def test_completeness_100_is_never_a_pass_when_exports_or_server_fail(self):
        cont = {"missing": [], "duplicated": [], "unexpected": []}; full = {"dates_meeting": 153, "dates_expected": 153, "percent": 100.0}
        v, why = chirps.verdict(0.95, {}, full, cont, ["2015-07-21: pixel size [1.0, 1.0] != native [0.05, 0.05]"])
        self.assertEqual(v, "STOP"); self.assertIn("no exported test image passed validation", " ".join(why))
        v, why = chirps.verdict(0.95, {"2015-12-01": 1.0}, full, cont, [], ["2015-07-21: coverage 1.0000 impossible"])
        self.assertEqual(v, "STOP"); self.assertIn("NOT verified", " ".join(why))
        self.assertEqual(chirps.verdict(0.95, {"2015-12-01": 1.0}, None, cont, [])[0], "STOP")                       # completeness not computed
        self.assertEqual(chirps.verdict(0.95, {"2015-12-01": 1.0}, full, cont, [], [])[0], "PROCEED-TO-REVIEW")



class FakeEEImage:                                    # stands in for ee.Image (not JSON serialisable, may carry credentials in real life)
    def __repr__(self): return "<ee.Image SECRET>"


class TestManifestSerialisation(unittest.TestCase):
    """Regression for `TypeError: Object of type Image is not JSON serializable` at probe_manifest.json: ee.Image.getDownloadURL mutates the dict it is given."""
    def test_real_ee_getDownloadURL_mutates_the_request_dict(self):
        try:
            import ee
        except ImportError:
            self.skipTest("earthengine-api not installed")
        from unittest import mock
        win = chirps.snap_window(TR, (80.134, 12.852, 80.333, 13.235), 1); wtr = chirps.window_transform(TR, win)
        req = chirps.download_params("EPSG:4326", wtr, (win[3], win[2]))
        before = chirps.sanitize_request(req)                          # what the probe records, taken BEFORE the call
        sent = dict(req); marker = object()
        with mock.patch.object(ee.data, "getDownloadId", side_effect=RuntimeError("stop after mutation")):
            with self.assertRaises(RuntimeError): ee.Image.getDownloadURL(marker, sent)        # real library code path, no network reached
        self.assertIs(sent.get("image"), marker)                       # CONFIRMED: the library inserts the image into the caller's dict
        self.assertNotIn("image", req)                                 # the pristine request is untouched because a copy was sent
        with self.assertRaises(TypeError): json.dumps(sent)            # ...and the mutated dict is what broke json.dumps
        self.assertNotIn("image", before); json.dumps(before)

    def test_sanitize_request_whitelists_and_rejects(self):
        req = {"crs": "EPSG:4326", "crs_transform": (0.05, 0.0, 1.0, 0.0, -0.05, 2.0), "dimensions": [7, 10], "format": "GEO_TIFF", "image": FakeEEImage(), "region": FakeEEImage(), "token": "x"}
        out = chirps.sanitize_request(req)
        self.assertEqual(set(out), {"crs", "crs_transform", "dimensions", "format"}); self.assertEqual(out["dimensions"], [7, 10]); json.dumps(out)
        with self.assertRaises(TypeError): chirps.sanitize_request({"crs": FakeEEImage()})

    def test_manifest_with_ee_image_in_request_serialises_without_leaking(self):
        req = chirps.download_params("EPSG:4326", TR, (10, 7)); sent = dict(req); sent["image"] = FakeEEImage()      # exactly what ee does
        rec = chirps.manifest_file_record(name="a.tif", date_iso="2015-07-21", sha256="ab", nbytes=10, mtime_utc="t", provenance="downloaded this run",
                                          request_sanitized=chirps.sanitize_request(req), request_note="n", http_status=200, content_type="image/tiff",
                                          url_host="https://x/y", info={"shape": [10, 7]}, problems=[])
        txt = json.dumps(chirps.json_safe({"files": [rec]})); self.assertNotIn("SECRET", txt); self.assertNotIn("image", json.loads(txt)["files"][0]["request_params"])
        # belt and braces: even if a bad object reaches the manifest, it is dropped (type only) and reported, never raised, never leaked
        dropped = []; bad = chirps.json_safe({"files": [{"request_params": sent, "url": "https://ee/download?id=1&token=SECRET"}]}, "$", dropped)
        txt = json.dumps(bad); self.assertNotIn("SECRET", txt); self.assertEqual(dropped, [{"path": "$.files[0].request_params.image", "type": "FakeEEImage"}])
        self.assertEqual(bad["files"][0]["url"], "https://ee/download")

    def test_json_safe_handles_numpy_affine_nan_dates_paths(self):
        out = chirps.json_safe({"a": np.float32(1.5), "b": np.int64(3), "c": np.array([1.0, np.nan]), "d": TR, "e": float("nan"), "f": date(2015, 7, 21), "g": Path("x/y"), "h": (1, 2)})
        json.dumps(out); self.assertEqual(out["b"], 3); self.assertEqual(out["c"], [1.0, None]); self.assertIsNone(out["e"]); self.assertEqual(out["f"], "2015-07-21")

    def test_script_copies_request_before_call_and_builds_manifest_from_scalars(self):
        src = (ROOT / "scripts" / "probe_chirps_coverage.py").read_text(encoding="utf-8")
        self.assertLess(src.index("chirps.sanitize_request(req)"), src.index("getDownloadURL(dict(req))"))
        self.assertIn("chirps.manifest_file_record(", src); self.assertNotIn('"request_params": req,', src)
        for flag in ("--reuse-exports", "--reuse-server-cache"): self.assertIn(flag, src)
        self.assertIn("server_per_date_cache.json", src)                                           # per-date results are checkpointed before any output is written


if __name__ == "__main__":
    unittest.main()
