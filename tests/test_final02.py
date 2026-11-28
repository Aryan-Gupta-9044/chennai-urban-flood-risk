"""FINAL-02 regression tests: shared map frame, map data checks, integrity wording, ML-EXP-1.1 statistics, S1TC guard."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


class MapFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lib import maps
        cls.maps = maps
        m = maps.base_map()
        cls.html = maps.offline_html(m.get_root().render())

    def test_osm_default_no_carto(self):
        self.assertIn("tile.openstreetmap.org", self.html)
        self.assertNotIn("cartocdn", self.html.lower())
        self.assertNotIn("api_key", self.html.lower())

    def test_extent_bounded_and_no_wheel_zoom(self):
        self.assertIn('"scrollWheelZoom": false', self.html)
        self.assertIn("maxBounds", self.html)
        self.assertIn("fitBounds", self.html)
        x0, y0, x1, y1 = self.maps.aoi_extent_wgs84()
        self.assertTrue(80.0 < x0 < x1 < 80.5 and 12.7 < y0 < y1 < 13.4, (x0, y0, x1, y1))

    def test_metric_scale_banner_north(self):
        self.assertIn("imperial: false", self.html)
        self.assertIn("Basemap tiles could not be loaded", self.html)
        self.assertIn("north-arrow", self.html)

    def test_offline_assets_inlined(self):
        self.assertNotIn("cdn.jsdelivr.net/npm/leaflet", self.html)
        self.assertNotIn("url(images/layers.png)", self.html)

    def test_render_prefers_st_iframe(self):
        src = (ROOT / "dashboard/lib/maps.py").read_text(encoding="utf-8")
        self.assertIn("st.iframe(html, height=height)", src)


class MapData(unittest.TestCase):
    def test_ward_geometry_check(self):
        from lib import maps
        from lib.data import wards
        W = wards()
        if W is None:
            self.skipTest("wards GPKG not in this checkout")
        chk = maps.geometry_check(W, "ward_no")
        self.assertEqual(chk["n_features"], 200)
        self.assertTrue(chk["ok"], chk)

    def test_cluster_join_coverage(self):
        from lib.data import ward_table
        W = ward_table()
        if W is None or "cluster" not in W:
            self.skipTest("ML-EXP-1 outputs not in this checkout")
        self.assertEqual(int(W.ward_no.duplicated().sum()), 0)
        self.assertEqual(sorted(W.loc[W.cluster.isna(), "ward_no"].astype(int)), [134, 135])

    def test_display_geoms_repairs_and_projects(self):
        import geopandas as gpd
        from shapely.geometry import Polygon
        from lib import maps
        bow = Polygon([(406100, 1430000), (406200, 1430100), (406200, 1430000), (406100, 1430100)])   # self-intersecting
        g = gpd.GeoDataFrame({"ward_no": [1]}, geometry=[bow], crs="EPSG:32644")
        out = maps.display_geoms(g, ["ward_no"])
        self.assertTrue(out.geometry.is_valid.all())
        self.assertEqual(out.crs.to_epsg(), 4326)

    def test_quantile_fmt(self):
        from lib import maps
        self.assertEqual(maps._fmt(12345.6), "12,346")
        self.assertEqual(maps._fmt(0.1234), "0.12")


class IntegrityWording(unittest.TestCase):
    def test_guard_text_counts_records(self):
        from lib import ui
        rec = {"inputs_unchanged": True, "input_hashes": {"a\\b\\x.tif": "1", "c/y.csv": "2", "z.tif": "3", "w.tif": "4"}}
        txt, tip = ui.guard_text(rec)
        self.assertEqual(txt, "4 guarded inputs unchanged")
        self.assertIn("x.tif", tip)
        self.assertIn("Other inputs were not hash-guarded", tip)
        self.assertIn("CHANGED", ui.guard_text({"inputs_unchanged": False, "input_hashes": {"a": "1"}})[0])
        self.assertEqual(ui.guard_text({})[0], "no input guard recorded")

    def test_no_bare_inputs_unchanged_true_in_ui(self):
        for f in (ROOT / "dashboard/sections").glob("*.py"):
            self.assertNotIn('("inputs unchanged", str(', f.read_text(encoding="utf-8"), f.name)


class ReviewStatistics(unittest.TestCase):
    def test_within_zone_auc(self):
        from analytics.pb_review import within_zone_auc
        y = np.array([1, 0, 1, 0, 1, 0])
        s = np.array([0.9, 0.1, 0.2, 0.8, 0.5, 0.5])
        z = np.array([1, 1, 2, 2, 3, 3])
        wz, per = within_zone_auc(y, s, z)
        self.assertEqual(list(per), [1.0, 0.0, 0.5])
        self.assertAlmostEqual(wz, 0.5)

    def test_zone_offsets_do_not_affect_within_zone(self):
        from analytics.pb_review import within_zone_auc
        from analytics.presence_only import pb_auc
        rng = np.random.default_rng(1)
        z = np.repeat(np.arange(10), 20)
        y = (rng.random(200) < np.repeat(np.linspace(0.2, 0.8, 10), 20)).astype(int)
        s = y * 0.3 + rng.random(200) * 0.2 - np.repeat(np.linspace(0, 2, 10), 20)   # perfect within zones, big offsets between zones
        self.assertEqual(within_zone_auc(y, s, z)[0], 1.0)
        self.assertLess(pb_auc(y, s), 0.9)

    def test_stratified_permutation_keeps_zone_prevalence(self):
        from analytics.pb_review import _perm
        rng = np.random.default_rng(0)
        z = np.repeat([1, 2, 3], 10)
        y = np.r_[np.ones(9), np.zeros(1), np.ones(2), np.zeros(8), np.ones(5), np.zeros(5)].astype(int)
        yp = _perm(y, z, rng, stratified=True)
        for k in (1, 2, 3):
            self.assertEqual(yp[z == k].sum(), y[z == k].sum())

    def test_holm_bh(self):
        from analytics.pb_review import bh, holm
        p = np.array([0.01, 0.04, 0.03, 0.2])
        np.testing.assert_allclose(holm(p), [0.04, 0.09, 0.09, 0.2])
        np.testing.assert_allclose(bh(p), [0.04, 0.0533333, 0.0533333, 0.2], rtol=1e-5)


class NewRunsGuarded(unittest.TestCase):
    def test_s1tc_refuses_protected_outdir(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("s1tc", ROOT / "scripts/build_s1_temporal_context.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with self.assertRaises(SystemExit):
            mod.guard(ROOT / "outputs/s1_water_candidates_review_v2/x")

    def test_ml_review_refuses_ml_exp1_outdir(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mlr", ROOT / "scripts/build_ml_review.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with self.assertRaises(SystemExit):
            mod.guard(ROOT / "outputs/ml_exploratory_v1")

    def test_recorded_runs_kept_inputs(self):
        for p in (ROOT / "outputs/s1_temporal_context_v1/s1tc_summary.json", ROOT / "outputs/ml_review_v1_1/ml_review_summary.json"):
            if p.is_file():
                s = json.loads(p.read_text(encoding="utf-8"))
                self.assertTrue(s["inputs_unchanged"], p)
                self.assertTrue(all("\\" not in k for k in s["input_hashes"]), "paths must be POSIX")


if __name__ == "__main__":
    unittest.main()
