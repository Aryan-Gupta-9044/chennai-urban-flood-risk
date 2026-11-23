"""S1B tests (V2.2). Everything here is LOGIC testing on the pinned real scene IDs or on SYNTHETIC arrays.
No Earth Engine call is made: the EE graph / download are NOT covered and remain untested until a live Windows run.
Gate fixture rows reproduce the live EE check the user reported (5/5 FOUND, exact id, DESCENDING, rel orbit 92); polarisation
text ['VV','VH'] is the usual EE value (assumed format)."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
import geopandas as gpd
from src.utils import paths
from src.geospatial.grid import make_master_grid
from src.flood_detection import s1_gate, s1_params, s1_proxy, s1_report
from src.flood_detection.s1_orbits import relative_from_absolute, parse_scene_name
from src.flood_detection.s1_params import NODATA

EV = s1_params.load_events()
E = next(e for e in EV["events"] if e["id"] == "2015_nov")
ABS = {"20150820": 7339, "20150901": 7514, "20151019": 8214, "20151031": 8389, "20151112": 8564}


def good_rows():
    rows = []
    for sid in E["scene_ids"]["pre"] + E["scene_ids"]["post"]:
        d = parse_scene_name(sid)["start_date"]
        rows.append({"scene": sid, "date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "catalogue_direction": "DESCENDING", "status": "FOUND",
                     "match_method": "exact", "gee_id": sid, "gee_rel_orbit": 92, "gee_pass": "DESCENDING", "gee_polarisation": "['VV', 'VH']"})
    return rows


class TestConfig(unittest.TestCase):
    def test_five_unique_pinned_scenes(self):
        pre, post = E["scene_ids"]["pre"], E["scene_ids"]["post"]
        self.assertEqual((len(pre), len(post)), (4, 1))
        self.assertEqual(len(set(pre + post)), 5)

    def test_dates_and_orbits_match_formula(self):
        for sid in E["scene_ids"]["pre"] + E["scene_ids"]["post"]:
            i = parse_scene_name(sid)
            self.assertEqual(i["clean_name"], sid)
            self.assertEqual(i["abs_orbit"], ABS[i["start_date"]])
            self.assertEqual(relative_from_absolute(i["platform_code"], i["abs_orbit"])[0], 92)
        self.assertEqual(parse_scene_name(E["scene_ids"]["post"][0])["start_date"], "20151112")
        self.assertTrue(all(parse_scene_name(s)["start_date"] < "20151112" for s in E["scene_ids"]["pre"]))

    def test_event_is_exploratory(self):
        self.assertEqual(E["role"], "exploratory")


class TestGate(unittest.TestCase):
    def test_pass(self):
        g = s1_gate.verify_scenes(E, good_rows())
        self.assertTrue(g["ok"], g["problems"])
        self.assertEqual(len(g["scenes"]), 5)

    def _mut(self, fn):
        rows = good_rows(); fn(rows)
        return s1_gate.verify_scenes(E, rows)

    def test_missing_scene_blocks(self):
        g = self._mut(lambda r: r.pop(2))
        self.assertFalse(g["ok"])

    def test_not_found_blocks(self):
        self.assertFalse(self._mut(lambda r: r[0].update(status="NOT FOUND"))["ok"])

    def test_wrong_relative_orbit_blocks(self):
        self.assertFalse(self._mut(lambda r: r[1].update(gee_rel_orbit=164))["ok"])

    def test_wrong_direction_blocks(self):
        self.assertFalse(self._mut(lambda r: r[4].update(gee_pass="ASCENDING"))["ok"])

    def test_missing_vv_blocks(self):
        self.assertFalse(self._mut(lambda r: r[3].update(gee_polarisation="['HH', 'HV']"))["ok"])

    def test_id_mismatch_and_non_exact_block(self):
        self.assertFalse(self._mut(lambda r: r[0].update(gee_id="OTHER"))["ok"])
        self.assertFalse(self._mut(lambda r: r[0].update(match_method="time_window"))["ok"])

    def test_date_mismatch_blocks(self):
        self.assertFalse(self._mut(lambda r: r[0].update(date="2015-08-21"))["ok"])

    def test_duplicate_row_blocks(self):
        self.assertFalse(self._mut(lambda r: r.append(dict(r[0])))["ok"])

    def test_too_few_pre_blocks(self):
        e = copy.deepcopy(E); e["scene_ids"]["pre"] = e["scene_ids"]["pre"][:2]
        self.assertFalse(s1_gate.verify_scenes(e, good_rows())["ok"])

    def test_two_post_blocks(self):
        e = copy.deepcopy(E); e["scene_ids"]["post"] = e["scene_ids"]["post"] + [e["scene_ids"]["pre"][0]]
        self.assertFalse(s1_gate.verify_scenes(e, good_rows())["ok"])

    def test_pre_after_post_blocks(self):
        e = copy.deepcopy(E); e["scene_ids"]["pre"][0], e["scene_ids"]["post"][0] = e["scene_ids"]["post"][0], e["scene_ids"]["pre"][0]
        self.assertFalse(s1_gate.verify_scenes(e, good_rows())["ok"])

    def test_wrong_config_orbit_blocks(self):
        e = copy.deepcopy(E); e["orbit"]["rel_orbit"] = 164
        self.assertFalse(s1_gate.verify_scenes(e, good_rows())["ok"])


class TestParams(unittest.TestCase):
    def setUp(self):
        self.grid = make_master_grid((400000, 1430000, 400600, 1430600))

    def test_defaults_and_override(self):
        p = s1_params.get_params()
        self.assertEqual(p["diff_threshold_db"], -3.0)
        self.assertEqual(s1_params.get_params({"diff_threshold_db": "-2.5"})["diff_threshold_db"], -2.5)
        self.assertIsNone(s1_params.get_params({"max_hand_m": "none"})["max_hand_m"])

    def test_unknown_param(self):
        with self.assertRaises(KeyError):
            s1_params.get_params({"nope": 1})

    def test_run_id_stable_and_sensitive(self):
        ids = E["scene_ids"]; p = s1_params.get_params()
        a = s1_params.run_id("2015_nov", ids, p, self.grid)
        self.assertEqual(a, s1_params.run_id("2015_nov", ids, p, self.grid))
        self.assertNotEqual(a, s1_params.run_id("2015_nov", ids, s1_params.get_params({"diff_threshold_db": -2.0}), self.grid))


class TestTiles(unittest.TestCase):
    def test_tiles_cover_grid_exactly_and_nest_30m(self):
        g = make_master_grid((400000, 1430000, 400930, 1430610))
        tiles = s1_proxy.tile_plan(g, 100)
        W, H = g.width * 3, g.height * 3
        cover = np.zeros((H, W), int)
        for t in tiles:
            cover[t["r0"]:t["r0"] + t["h"], t["c0"]:t["c0"] + t["w"]] += 1
            x0, yb, x1, yt, tr = s1_proxy.tile_geometry(t)
            self.assertEqual((x0 - g.transform.c) % 10, 0)
            self.assertAlmostEqual((x1 - x0) / 10, t["w"]); self.assertAlmostEqual((yt - yb) / 10, t["h"])
            self.assertEqual(tr, [10, 0, x0, 0, -10, yt])
        self.assertTrue((cover == 1).all())
        self.assertEqual((s1_proxy.tile_plan(g, 100)[0]["x0"], s1_proxy.tile_plan(g, 100)[0]["ytop"]), (g.transform.c, g.transform.f))

    def test_download_size_budget(self):
        self.assertLess(512 * 512 * len(s1_proxy.LAYERS) * 4, 48e6)

    def test_bad_resolution_ratio(self):
        g = make_master_grid((399990, 1430010, 400290, 1430310))
        with self.assertRaises(ValueError):
            s1_proxy.tile_plan(g, 100, res=7.0)


def synthetic_stack(H, W):
    """SYNTHETIC 10 m stack in LAYERS order. Not data."""
    L = {n: np.full((H, W), NODATA, "float32") for n in s1_proxy.LAYERS}
    L["valid"][:] = 1
    for n in ("candidate", "mask_prev_dark", "mask_perm_water", "mask_steep", "mask_hand", "flood_proxy"):
        L[n][:] = 0
    L["pre_median_db"][:] = -10; L["pre_std_db"][:] = 1; L["pre_count"][:] = 4; L["post_db"][:] = -10; L["diff_db"][:] = 0
    L["slope_deg"][:] = 0.5; L["hand_m"][:] = 3; L["water_occurrence_pct"][:] = 0
    return L


class TestAggregation(unittest.TestCase):
    def test_block_mean_ignores_nodata(self):
        a = np.array([[1, 1, 1, 2, 2, 2]] * 3, "float32"); a[0, 0] = NODATA
        out = s1_report.block_mean(a, 3)
        self.assertAlmostEqual(float(out[0, 0]), 1.0); self.assertAlmostEqual(float(out[0, 1]), 2.0)

    def test_block_mean_all_nodata(self):
        self.assertEqual(float(s1_report.block_mean(np.full((3, 3), NODATA, "float32"), 3)[0, 0]), NODATA)

    def test_block_mean_shape_error(self):
        with self.assertRaises(ValueError):
            s1_report.block_mean(np.zeros((4, 4)), 3)

    def test_aggregate_and_stats_synthetic(self):
        g = make_master_grid((399990, 1430010, 400140, 1430160), pad_cells=0)   # 5 x 5 cells
        H, W = g.height * 3, g.width * 3
        L = synthetic_stack(H, W)
        # cell (1,1): all 9 pixels flooded; cell (2,2): 4/9 flooded (below 0.5); cell (3,3): 5/9 flooded (>= 0.5)
        L["candidate"][3:6, 3:6] = 1; L["flood_proxy"][3:6, 3:6] = 1; L["diff_db"][3:6, 3:6] = -6
        L["candidate"][6:8, 6:8] = 1; L["flood_proxy"][6:8, 6:8] = 1
        L["flood_proxy"][9:12, 9:12].flat[:5] = 1; L["candidate"][9:12, 9:12].flat[:5] = 1
        # cell (0,4): candidate removed by permanent water
        L["candidate"][0:3, 12:15] = 1; L["mask_perm_water"][0:3, 12:15] = 1
        # cell (4,0): no valid SAR
        L["valid"][12:15, 0:3] = 0
        stack = np.stack([L[n] for n in s1_proxy.LAYERS])
        prod = s1_report.aggregate(stack, 3, 0.5)
        fl = prod["flood_proxy_30m"]
        self.assertEqual(int(fl[1, 1]), 1); self.assertEqual(int(fl[2, 2]), 0); self.assertEqual(int(fl[3, 3]), 1)
        self.assertEqual(int(fl[4, 0]), 255); self.assertEqual(int(fl[0, 4]), 0)
        self.assertEqual(float(prod["post_db"][4, 0]), NODATA)
        inside = np.ones((5, 5), bool)
        s = s1_report.compute_stats(stack, prod, inside, g, 3)
        self.assertEqual(s["flood_proxy_cells_30m"], 2)
        self.assertEqual(s["candidate_removed_by_permanent_water_10m"], 9)
        self.assertEqual(s["candidate_pixels_10m"], 9 + 4 + 5 + 9)
        self.assertEqual(s["no_valid_sar_cells_30m"], 1)
        self.assertEqual(s["flood_proxy_pixels_10m"], 9 + 4 + 5)
        self.assertAlmostEqual(s["flood_proxy_km2_30m"], 2 * 900 / 1e6, places=3)
        self.assertEqual(s["flood_proxy_by_hand_m"]["2-5"], 18)

    def test_assemble_checks_alignment(self):
        g = make_master_grid((399990, 1430010, 400080, 1430100), pad_cells=0)   # 3x3 cells, 9x9 at 10 m
        tiles = s1_proxy.tile_plan(g, 9)
        self.assertEqual(len(tiles), 1)
        t = tiles[0]
        arr = np.stack([np.full((9, 9), i, "float32") for i in range(len(s1_proxy.LAYERS))])
        with tempfile.TemporaryDirectory() as d:
            def wr(name, x0=t["x0"], n=len(arr)):
                p = Path(d) / name
                with rasterio.open(p, "w", driver="GTiff", height=9, width=9, count=n, dtype="float32", crs="EPSG:32644",
                                   transform=from_origin(x0, t["ytop"], 10, 10)) as ds:
                    ds.write(arr[:n])
                return p
            full = s1_report.assemble([wr("ok.tif")], tiles, g, 3)
            self.assertEqual(float(full[4, 0, 0]), 4.0)
            with self.assertRaises(ValueError):
                s1_report.assemble([wr("shift.tif", x0=t["x0"] + 10)], tiles, g, 3)
            with self.assertRaises(ValueError):
                s1_report.assemble([wr("bands.tif", n=5)], tiles, g, 3)


class TestEndToEndSynthetic(unittest.TestCase):
    def test_write_outputs_on_synthetic_stack(self):
        spec = importlib.util.spec_from_file_location("s1b_script", ROOT / "scripts" / "s1b_flood_extent.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        g = make_master_grid((399990, 1430010, 400290, 1430310), pad_cells=0)
        H, W = g.height * 3, g.width * 3
        L = synthetic_stack(H, W)
        L["candidate"][6:15, 6:15] = 1; L["flood_proxy"][6:15, 6:15] = 1; L["diff_db"][6:15, 6:15] = -6; L["post_db"][6:15, 6:15] = -20
        stack = np.stack([L[n] for n in s1_proxy.LAYERS])
        boundary = gpd.GeoDataFrame(geometry=[box(*g.bounds)], crs=g.crs)
        inside = np.ones(g.shape, bool)
        params = s1_params.get_params()
        meta = {"event": "2015_nov", "run_id": "synthetic", "generated": "x", "crs": g.crs, "processing_res_m": 10.0, "output_res_m": 30.0,
                "grid_shape": [g.height, g.width], "params": params, "scene_ids": E["scene_ids"], "ee_project": None, "mode": "SYNTHETIC TEST"}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            saved = (paths.OUT_MAPS, paths.OUT_REP, paths.OUT_TAB)
            paths.OUT_MAPS, paths.OUT_REP, paths.OUT_TAB = d / "m", d / "r", d / "t"
            for x in (paths.OUT_MAPS, paths.OUT_REP, paths.OUT_TAB):
                x.mkdir()
            try:
                scenes = s1_gate.verify_scenes(E, good_rows())["scenes"]
                stats, files = mod.write_outputs(stack, g, inside, boundary, meta, d / "run", params, E, scenes, "SYNTHETIC TEST")
                names = {Path(f).name for f in files}
                for need in ("flood_proxy_30m.tif", "flood_proxy_10m.tif", "flood_proxy_30m.geojson", "metadata.json",
                             "s1b_2015_nov_synthetic_report.html", "s1b_2015_nov_synthetic_flood_proxy.png", "pre_median_db_30m.tif"):
                    self.assertIn(need, names)
                self.assertEqual(stats["flood_proxy_cells_30m"], 9)
                with rasterio.open(d / "run" / "flood_proxy_30m.tif") as ds:
                    self.assertEqual(ds.res, (30.0, 30.0)); self.assertEqual(ds.crs.to_epsg(), 32644)
                    self.assertEqual(int((ds.read(1) == 1).sum()), 9)
                with rasterio.open(d / "run" / "flood_proxy_10m.tif") as ds:
                    self.assertEqual(ds.res, (10.0, 10.0)); self.assertEqual(int((ds.read(1) == 1).sum()), 81)
                md = json.loads((d / "run" / "metadata.json").read_text())
                self.assertEqual(md["label"], "SAR_PROXY_UNVALIDATED"); self.assertIn("no accuracy", md["validation"])
                html_txt = (paths.OUT_REP / "s1b_2015_nov_synthetic_report.html").read_text()
                for must in ("Not independently verified", "UNVALIDATED", E["scene_ids"]["post"][0], "EPSG:32644"):
                    self.assertIn(must.lower(), html_txt.lower())
                self.assertNotIn("accuracy:", html_txt.lower())
            finally:
                paths.OUT_MAPS, paths.OUT_REP, paths.OUT_TAB = saved


if __name__ == "__main__":
    unittest.main()
