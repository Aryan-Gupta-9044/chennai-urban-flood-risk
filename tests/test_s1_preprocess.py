"""M4C: Sentinel-1 date-level preprocessing logic. SYNTHETIC arrays/rasters only - these tests do NOT exercise Earth Engine or real Chennai imagery."""
import importlib.util
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import rasterio
from shapely.geometry import box
from src.geospatial.grid import make_master_grid, write_raster, inside_mask
from src.flood_detection import s1_preprocess as pp

CFGQ = {"min_aoi_valid_pct": 95.0, "extreme_low_db": -40.0, "extreme_high_db": 5.0, "power_ratio_tol": 0.05, "seam_width_m": 90.0, "seam_flag_db": 2.0}
GRID = make_master_grid((410000.0, 1440000.0, 410300.0, 1440300.0))        # synthetic projected bounds
EXP = {"crs": GRID.crs, "transform": tuple(GRID.transform)[:6], "shape": GRID.shape}


def _load_script():
    spec = importlib.util.spec_from_file_location("s1pp_script", ROOT / "scripts" / "s1_preprocess_2021.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class TestOverlapRule(unittest.TestCase):
    def test_permutation_invariant_bitwise(self):
        rng = np.random.default_rng(0)
        s = [rng.normal(-12, 3, (6, 7)) for _ in range(3)]; s[0][1, 1] = np.nan; s[2][1, 1] = np.nan; s[1][0, 0] = np.nan
        ref, nref = pp.combine_slices(s)
        for perm in itertools.permutations(s):
            o, n = pp.combine_slices(list(perm)); np.testing.assert_array_equal(o, ref); np.testing.assert_array_equal(n, nref)

    def test_rule_values(self):
        a = np.array([[-10.0, -10.0, np.nan, np.nan]]); b = np.array([[-20.0, np.nan, -15.0, np.nan]])
        o, n = pp.combine_slices([a, b])
        self.assertAlmostEqual(o[0, 0], 10 * np.log10((0.1 + 0.01) / 2), places=9)       # linear-power mean, NOT the dB mean (-15)
        self.assertNotAlmostEqual(o[0, 0], -15.0, places=2)
        self.assertEqual(o[0, 1], -10.0); self.assertEqual(o[0, 2], -15.0)                 # one valid slice -> that slice
        self.assertTrue(np.isnan(o[0, 3])); self.assertEqual(n.tolist(), [[2, 1, 1, 0]])    # none valid -> NaN, never 0

    def test_sentinel_counts_as_invalid(self):
        o, n = pp.combine_slices([np.array([[-9999.0, -8.0]]), np.array([[-9999.0, -8.0]])]); self.assertTrue(np.isnan(o[0, 0])); self.assertEqual(o[0, 1], -8.0)


class TestPolarisations(unittest.TestCase):
    def test_vv_and_vh_independent(self):
        vv = [np.full((3, 3), -10.0), np.full((3, 3), -12.0)]; vh1 = [np.full((3, 3), -20.0), np.full((3, 3), -22.0)]
        vh2 = [np.full((3, 3), -20.0), np.full((3, 3), np.nan)]
        a, _ = pp.combine_slices(vv); b, _ = pp.combine_slices(vh1); c, nc = pp.combine_slices(vh2)
        a2, _ = pp.combine_slices(vv); np.testing.assert_array_equal(a, a2)                # VV unaffected by VH inputs (separate calls, no shared state)
        self.assertTrue(np.all(c == -20.0)); self.assertTrue(np.all(nc == 1)); self.assertNotEqual(b[0, 0], c[0, 0])

    def test_missing_polarisation_not_filled(self):
        sc = [{"id": "a", "bands": ["VV", "VH", "angle"]}, {"id": "b", "bands": ["VV", "angle"]}]
        p = pp.pol_plan(sc); self.assertTrue(p["VV"]["producible"]); self.assertFalse(p["VH"]["producible"]); self.assertEqual(p["VH"]["missing_in"], ["b"])
        self.assertFalse(pp.pol_plan([])["VV"]["producible"])

    def test_scene_identity(self):
        exp = {"platform": "SENTINEL-1A", "pass": "DESCENDING", "rel_orbit": 92, "mode": "IW", "n_slices": 2}
        t = 1636936260000   # 2021-11-15T00:31 UTC? (checked below)
        d = pp.utc_date(t)
        mk = lambda i, **k: dict({"id": i, "t": t, "platform": "A", "pass": "DESCENDING", "rel_orbit": 92, "mode": "IW", "bands": ["VV", "VH"]}, **k)   # noqa: E731
        self.assertEqual(pp.verify_scene_identity(d, ["a", "b"], [mk("a"), mk("b")], exp), [])
        self.assertTrue(pp.verify_scene_identity(d, ["a", "b"], [mk("a"), mk("b", platform="B")], exp))
        self.assertTrue(pp.verify_scene_identity(d, ["a", "b"], [mk("a"), mk("b", rel_orbit=33)], exp))
        self.assertTrue(pp.verify_scene_identity(d, ["a", "b"], [mk("a"), mk("b", **{"pass": "ASCENDING"})], exp))
        self.assertTrue(pp.verify_scene_identity("2021-01-01", ["a", "b"], [mk("a"), mk("b")], exp))                 # wrong acquisition date
        self.assertTrue(pp.verify_scene_identity(d, ["a", "b"], [mk("a"), mk("c")], exp))                            # not the inventory ids
        self.assertTrue(pp.verify_scene_identity(d, ["a"], [mk("a")], exp))                                           # one slice only


class TestNoDataAndGrid(unittest.TestCase):
    def test_nodata_never_zero_and_zero_db_is_data(self):
        a = np.array([[np.nan, 0.0, -12.5, np.inf]]); o = pp.to_nodata(a)
        self.assertEqual(o[0, 0], pp.NODATA); self.assertEqual(o[0, 1], 0.0); self.assertEqual(o[0, 3], pp.NODATA); self.assertEqual(o.dtype, np.float32)
        vm = pp.valid_mask(np.array([[pp.NODATA, 0.0, -12.5, -5.0]]), np.array([[0.0, 1.0, 1.0, 0.2]]), 0.5)
        self.assertEqual(vm.tolist(), [[False, True, True, False]])                                                  # sentinel, low valid fraction invalid; 0 dB valid

    def test_roundtrip_preserves_sentinel(self):
        with tempfile.TemporaryDirectory() as d:
            arr = np.full(GRID.shape, -12.0); arr[2:4, 2:4] = np.nan
            write_raster(Path(d) / "x.tif", pp.to_nodata(arr), GRID, pp.NODATA, "x", "float32")
            with rasterio.open(Path(d) / "x.tif") as ds:
                r = ds.read(1); self.assertEqual(ds.nodata, pp.NODATA); self.assertTrue(np.all(r[2:4, 2:4] == pp.NODATA)); self.assertFalse(np.any(r == 0.0))

    def _qa(self, db=None, vf=None, grid_info=None, inside=None, source=None):
        db = np.full(GRID.shape, -12.0) if db is None else db; vf = np.ones(GRID.shape) if vf is None else vf
        inside = np.ones(GRID.shape, bool) if inside is None else inside
        return pp.qa_product(db, vf, grid_info or EXP, EXP, inside, CFGQ, 0.5, source)

    def test_qa_pass_and_grid_failures(self):
        m, f = self._qa(source={"mean_linear": float(np.power(10, -1.2))}); self.assertEqual(f, []); self.assertAlmostEqual(m["power_ratio_out_over_source"], 1.0, places=6)
        self.assertTrue(any("CRS" in x for x in self._qa(grid_info=dict(EXP, crs="EPSG:4326"))[1]))
        self.assertTrue(any("transform" in x for x in self._qa(grid_info=dict(EXP, transform=(30.0, 0, EXP["transform"][2] + 15, 0, -30.0, EXP["transform"][5])))[1]))
        self.assertTrue(any("shape" in x for x in self._qa(grid_info=dict(EXP, shape=(5, 5)))[1]))

    def test_qa_detects_low_valid_zero_fill_nan_and_power_mismatch(self):
        db = np.full(GRID.shape, -12.0); vf = np.ones(GRID.shape); db[:, : GRID.width // 2] = pp.NODATA; vf[:, : GRID.width // 2] = 0
        self.assertTrue(any("AOI valid" in x for x in self._qa(db, vf)[1]))
        db = np.full(GRID.shape, -12.0); vf = np.ones(GRID.shape); db[3, 3] = 0.0; vf[3, 3] = 0.0                       # a 0 where invalid = zero-fill
        self.assertTrue(any("zero-fill" in x for x in self._qa(db, vf)[1]))
        db = np.full(GRID.shape, -12.0); db[1, 1] = np.nan; self.assertTrue(any("NaN" in x for x in self._qa(db)[1]))
        self.assertTrue(any("power ratio" in x for x in self._qa(source={"mean_linear": 1.0})[1]))
        db = np.full(GRID.shape, -12.0); db[0, 0] = -60.0; db[0, 1] = 9.0; m, f = self._qa(db); self.assertEqual((m["extreme_low_cells"], m["extreme_high_cells"]), (1, 1))

    def test_script_export_grid_check(self):
        s = _load_script(); from rasterio.io import MemoryFile
        from rasterio.transform import from_origin
        def tif(transform, shape=GRID.shape, count=2):
            with MemoryFile() as mf:
                with mf.open(driver="GTiff", height=shape[0], width=shape[1], count=count, dtype="float32", crs=GRID.crs, transform=transform) as ds:
                    for i in range(count): ds.write(np.full(shape, i, "float32"), i + 1)
                return mf.read()
        self.assertEqual(len(s.read_pack(tif(GRID.transform), GRID, 2)), 2)
        with self.assertRaises(RuntimeError): s.read_pack(tif(from_origin(GRID.transform.c + 10, GRID.transform.f, 30, 30)), GRID, 2)
        with self.assertRaises(RuntimeError): s.read_pack(tif(GRID.transform, shape=(5, 5)), GRID, 2)
        with self.assertRaises(RuntimeError): s.read_pack(tif(GRID.transform, count=1), GRID, 2)


class TestSeam(unittest.TestCase):
    def test_overlap_diff_stats(self):
        a = np.array([[-10.0, -10.0, np.nan]]); b = np.array([[-12.0, np.nan, -9.0]]); s = pp.overlap_diff_stats(a, b)
        self.assertEqual(s["n_overlap_px"], 1); self.assertAlmostEqual(s["mean_diff_db"], 2.0)
        z = pp.overlap_diff_stats(a, np.full((1, 3), np.nan)); self.assertEqual(z["n_overlap_px"], 0); self.assertIsNone(z["mean_abs_diff_db"])   # no overlap -> None, not 0

    def test_seam_zone_and_flag(self):
        import geopandas as gpd
        aoi_utm = box(*GRID.bounds); aoi_wgs = gpd.GeoSeries([aoi_utm], crs=GRID.crs).to_crs(4326).iloc[0]
        ymid = (GRID.bounds[1] + GRID.bounds[3]) / 2
        fa = gpd.GeoSeries([box(GRID.bounds[0] - 500, ymid, GRID.bounds[2] + 500, GRID.bounds[3] + 500)], crs=GRID.crs).to_crs(4326).iloc[0]
        fb = gpd.GeoSeries([box(GRID.bounds[0] - 500, GRID.bounds[1] - 500, GRID.bounds[2] + 500, ymid)], crs=GRID.crs).to_crs(4326).iloc[0]
        z = pp.seam_zone(GRID, fa, fb, aoi_wgs, 90.0)
        rows = np.where(z.any(axis=1))[0]; self.assertTrue(len(rows) >= 2); self.assertLess(len(rows), GRID.height)      # a strip around the shared edge only
        inside = np.ones(GRID.shape, bool); db = np.full(GRID.shape, -12.0); valid = np.ones(GRID.shape, bool)
        self.assertFalse(pp.seam_diag(db, valid, z, inside, 2.0)["flag"])
        db2 = db.copy(); db2[z] = -18.0; d = pp.seam_diag(db2, valid, z, inside, 2.0); self.assertTrue(d["flag"]); self.assertAlmostEqual(d["zone_minus_rest_db"], -6.0)
        v2 = valid.copy(); v2[z] = False; d = pp.seam_diag(db, v2, z, inside, 2.0); self.assertIsNone(d["flag"]); self.assertEqual(d["seam_zone_valid_pct"], 0.0)
        e = pp.seam_diag(db, valid, np.zeros(GRID.shape, bool), inside, 2.0); self.assertEqual(e["seam_zone_cells"], 0); self.assertIsNone(e["flag"])


class TestFailuresAndReruns(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.sp = self.tmp / "state.json"; self.calls = []

    def exporter(self, fail=()):
        def f(d):
            self.calls.append(d)
            if d in fail: raise RuntimeError("simulated Earth Engine request failure")
            (self.tmp / f"{d}_VV.tif").write_bytes(f"data-{d}".encode()); (self.tmp / f"{d}_meta.json").write_text("{}")
            return {"files": [f"{d}_VV.tif", f"{d}_meta.json"], "meta_file": f"{d}_meta.json"}
        return f

    def test_retry_helper(self):
        n = {"k": 0}; sl = []
        def flaky():
            n["k"] += 1
            if n["k"] < 3: raise ConnectionError("boom")
            return b"ok"
        self.assertEqual(pp.download_with_retry(flaky, 3, 1.0, sl.append), b"ok"); self.assertEqual(sl, [1.0, 2.0])
        with self.assertRaises(RuntimeError) as c: pp.download_with_retry(lambda: (_ for _ in ()).throw(ValueError("x")), 2, 0, lambda s: None)
        self.assertIn("after 2 attempts", str(c.exception))

    def test_failure_isolated_and_recorded(self):
        sig = {"d1": "s1", "d2": "s2", "d3": "s3"}
        r = pp.run_dates(["d1", "d2", "d3"], sig, self.exporter(fail={"d2"}), self.tmp, self.sp)
        self.assertEqual(r, {"d1": "EXPORTED", "d2": "FAILED", "d3": "EXPORTED"}); st = pp.load_state(self.sp)
        self.assertEqual(st["d2"]["status"], "FAILED"); self.assertIn("simulated", st["d2"]["error"]); self.assertEqual(st["d2"]["files"], {})
        self.calls.clear(); r2 = pp.run_dates(["d1", "d2", "d3"], sig, self.exporter(), self.tmp, self.sp)                 # rerun: only the failed date runs
        self.assertEqual(self.calls, ["d2"]); self.assertEqual(r2["d1"], "SKIPPED_UP_TO_DATE"); self.assertEqual(pp.load_state(self.sp)["d2"]["status"], "EXPORTED")

    def test_modified_or_missing_file_triggers_repair_not_reuse(self):
        sig = {"d1": "s1"}; pp.run_dates(["d1"], sig, self.exporter(), self.tmp, self.sp); self.calls.clear()
        (self.tmp / "d1_VV.tif").write_bytes(b"tampered"); self.assertEqual(pp.run_dates(["d1"], sig, self.exporter(), self.tmp, self.sp)["d1"], "EXPORTED"); self.assertEqual(self.calls, ["d1"])
        self.calls.clear(); (self.tmp / "d1_VV.tif").unlink(); pp.run_dates(["d1"], sig, self.exporter(), self.tmp, self.sp); self.assertEqual(self.calls, ["d1"])

    def test_stale_signature_never_silently_reused(self):
        pp.run_dates(["d1"], {"d1": "old"}, self.exporter(), self.tmp, self.sp); self.calls.clear()
        r = pp.run_dates(["d1"], {"d1": "new"}, self.exporter(), self.tmp, self.sp)
        self.assertEqual(r["d1"], "STALE_NOT_RERUN"); self.assertEqual(self.calls, []); self.assertEqual((self.tmp / "d1_VV.tif").read_bytes(), b"data-d1")   # untouched
        r = pp.run_dates(["d1"], {"d1": "new"}, self.exporter(), self.tmp, self.sp, force_stale=True)
        self.assertEqual(r["d1"], "EXPORTED"); self.assertTrue((self.tmp / "_superseded" / "old" / "d1_VV.tif").exists())                                        # moved, not deleted
        self.assertEqual(pp.load_state(self.sp)["d1"]["signature"], "new")

    def test_signature_changes_with_parameters_scenes_grid_aoi(self):
        base = dict(date="2021-11-16", slice_ids=["a", "b"], params={"min_valid_fraction": 0.5}, grid=GRID, aoi_fingerprint="f1", collection="C")
        s0 = pp.run_signature(**base)
        self.assertEqual(s0, pp.run_signature(**dict(base, slice_ids=["b", "a"])))                        # slice order irrelevant
        for k, v in (("params", {"min_valid_fraction": 0.6}), ("slice_ids", ["a", "c"]), ("aoi_fingerprint", "f2"), ("collection", "D"), ("grid", make_master_grid((410000.0, 1440000.0, 410600.0, 1440300.0)))):
            self.assertNotEqual(s0, pp.run_signature(**dict(base, **{k: v})), k)


class TestMetadataAndConfig(unittest.TestCase):
    def md(self):
        return {k: "x" for k in pp.REQUIRED_META}

    def test_metadata_completeness(self):
        self.assertEqual(pp.metadata_problems(self.md()), [])
        for k in pp.REQUIRED_META:
            m = self.md(); del m[k]; self.assertEqual(pp.metadata_problems(m), [k])
        m = self.md(); m["source_scene_ids"] = []; self.assertEqual(pp.metadata_problems(m), ["source_scene_ids"])

    def test_plan_from_coverage(self):
        rows = [{"date_utc": "2021-11-16", "slice_ids": "a;b"}, {"date_utc": "2021-11-04", "slice_ids": "c;d"}]
        self.assertEqual(pp.plan_from_coverage(rows, ["2021-11-16"]), {"2021-11-16": ["a", "b"]})
        with self.assertRaises(ValueError): pp.plan_from_coverage(rows, ["2021-11-17"])                                # never invented

    def test_config_and_script_claims(self):
        cfg = json.loads((ROOT / "config" / "s1_preprocess.json").read_text())
        self.assertEqual(cfg["dates"], ["2021-09-05", "2021-09-17", "2021-09-29", "2021-10-11", "2021-10-23", "2021-11-04", "2021-11-16", "2021-11-28"])
        self.assertIn("NOT applied", cfg["earth_engine_processing_claims"]["radiometric_terrain_flattening"]); self.assertIn("NOT confirmed", cfg["earth_engine_processing_claims"]["border_noise_removal"])
        s = (ROOT / "scripts" / "s1_preprocess_2021.py").read_text(encoding="utf-8")
        self.assertEqual(s.count("unmask(0)"), 1); self.assertIn('db30.unmask(cfg["nodata"])', s)                       # dB is never zero-filled; only the valid FRACTION uses 0
        self.assertIn("ee.Filter.inList", s); self.assertIn("verify_scene_identity", s); self.assertIn("--force-stale", s); self.assertIn("first_live_date", s)
        self.assertNotIn("flood_extent", s); self.assertNotIn("dry baseline", s.lower().replace("no baseline", ""))


class TestReducerKeys(unittest.TestCase):
    def test_pick_handles_both_naming_styles_without_p5_p50_confusion(self):
        s = _load_script()
        self.assertEqual(s.pick({"VV_p5": 1, "VV_p50": 2}, "p5"), 1); self.assertEqual(s.pick({"p5": 1, "p50": 2}, "p50"), 2)
        self.assertEqual(s.pick({"x_mean": 3}, "mean"), 3); self.assertIsNone(s.pick({"x_mean": 3}, "count")); self.assertIsNone(s.pick(None, "mean"))


if __name__ == "__main__":
    unittest.main()


# ====================================================================== M4C single-date QA corrections
import contextlib
import io
from unittest import mock

import pandas as pd

ID_A = "S1A_IW_GRDH_1SDV_20211116T003147_20211116T003212_040589_04D094_DB41"
ID_B = "S1A_IW_GRDH_1SDV_20211116T003212_20211116T003237_040589_04D094_B07B"
DATES8 = ["2021-09-05", "2021-09-17", "2021-09-29", "2021-10-11", "2021-10-23", "2021-11-04", "2021-11-16", "2021-11-28"]


def _qrows(date, sig="s", st=("QA_PASS", "QA_PASS")):
    return [{"date_utc": date, "pol": p, "status": s_, "run_signature": sig} for p, s_ in zip(pp.POLS, st)]


class TestStatusLogic(unittest.TestCase):
    def test_date_status(self):
        self.assertEqual(pp.date_status(_qrows("d")), "QA_PASS")
        self.assertEqual(pp.date_status(_qrows("d", st=("QA_PASS", "QA_FAIL"))), "QA_FAIL")
        self.assertEqual(pp.date_status(_qrows("d", st=("QA_PASS", "NOT_PRODUCED"))), "QA_FAIL")           # a missing polarisation is never a pass
        self.assertEqual(pp.date_status(_qrows("d", st=("FAILED", "FAILED"))), "FAILED")
        self.assertEqual(pp.date_status(_qrows("d")[:1]), "QA_FAIL")                                          # only one pol row present
        self.assertEqual(pp.date_status([]), "NOT_RUN")

    def test_one_date_never_completes_overall(self):
        sigs = {d: "s" for d in DATES8}
        o = pp.overall_status(_qrows("2021-11-16"), DATES8, sigs)
        self.assertFalse(o["complete"]); self.assertEqual((o["n_pass"], o["n_total"]), (1, 8)); self.assertEqual(o["per_date"]["2021-11-16"], "QA_PASS")
        self.assertEqual(o["per_date"]["2021-09-05"], "NOT_RUN"); self.assertEqual(len(o["missing"]), 7)

    def test_overall_complete_only_when_all_eight_pass_both_pols(self):
        sigs = {d: "s" for d in DATES8}; rows = [r for d in DATES8 for r in _qrows(d)]
        self.assertTrue(pp.overall_status(rows, DATES8, sigs)["complete"])
        bad = [r for d in DATES8 for r in _qrows(d, st=("QA_PASS", "QA_FAIL") if d == "2021-10-11" else ("QA_PASS", "QA_PASS"))]
        o = pp.overall_status(bad, DATES8, sigs); self.assertFalse(o["complete"]); self.assertEqual(o["n_pass"], 7)
        stale = [r for d in DATES8 for r in _qrows(d, sig="old" if d == "2021-11-04" else "s")]
        o = pp.overall_status(stale, DATES8, sigs); self.assertFalse(o["complete"]); self.assertEqual(o["per_date"]["2021-11-04"], "STALE")      # old configuration does not count
        self.assertFalse(pp.overall_status([], [], {})["complete"])

    def test_merge_qa_keeps_other_dates(self):
        old = _qrows("2021-09-05") + _qrows("2021-11-16", st=("QA_FAIL", "QA_FAIL")); new = _qrows("2021-11-16")
        m = pp.merge_qa(old, new)
        self.assertEqual({(r["date_utc"], r["status"]) for r in m}, {("2021-09-05", "QA_PASS"), ("2021-11-16", "QA_PASS")}); self.assertEqual(len(m), 4)


class TestMetadataFinalisation(unittest.TestCase):
    def test_finalize_updates_metadata_only_and_state_stays_consistent(self):
        tmp = Path(tempfile.mkdtemp()); sp = tmp / "state.json"; (tmp / "d_VV.tif").write_bytes(b"RASTER")
        def exporter(d):
            md = {k: "x" for k in pp.REQUIRED_META}; md["status"] = "EXPORTED (QA pending)"; (tmp / "d_meta.json").write_text(json.dumps(md))
            return {"files": ["d_VV.tif", "d_meta.json"], "meta_file": "d_meta.json"}
        pp.run_dates(["d"], {"d": "sig"}, exporter, tmp, sp)
        raster_before = pp.sha256_file(tmp / "d_VV.tif"); st = pp.load_state(sp)
        new_sha = pp.finalize_metadata(tmp / "d_meta.json", "QA_PASS", _qrows("d"), "2026-11-24T00:00:00Z")
        md = json.loads((tmp / "d_meta.json").read_text())
        self.assertEqual(md["status"], "QA_PASS"); self.assertEqual(md["export_status"], "EXPORTED (QA pending)"); self.assertEqual(md["qa"]["per_pol"]["VV"]["status"], "QA_PASS")
        self.assertEqual(pp.sha256_file(tmp / "d_VV.tif"), raster_before)                                            # raster untouched
        calls = []
        self.assertEqual(pp.decide(st["d"], "sig", tmp), "REPAIR")                                                   # without the sha refresh the edit would look like tampering
        st["d"]["files"]["d_meta.json"] = new_sha; st["d"]["status"] = "QA_PASS"; pp.save_state(sp, st)
        r = pp.run_dates(["d"], {"d": "sig"}, lambda d: calls.append(d), tmp, sp); self.assertEqual(r["d"], "SKIPPED_UP_TO_DATE"); self.assertEqual(calls, [])
        again = pp.finalize_metadata(tmp / "d_meta.json", "QA_FAIL", _qrows("d", st=("QA_PASS", "QA_FAIL")), "t2")
        self.assertEqual(json.loads((tmp / "d_meta.json").read_text())["export_status"], "EXPORTED (QA pending)"); self.assertNotEqual(again, new_sha)   # original export state preserved


class TestEndToEndReporting(unittest.TestCase):
    """Drives scripts/s1_preprocess_2021.py main() with a SYNTHETIC exporter (no Earth Engine): report / CSV / metadata / state must agree."""
    def setUp(self):
        import types
        import geopandas as gpd
        from shapely.geometry import mapping
        self.s = _load_script(); s = self.s; tmp = self.tmp = Path(tempfile.mkdtemp())
        for x in ("t", "r", "f", "p"): (tmp / x).mkdir()
        self.aoi = box(80.18, 13.00, 80.24, 13.06); self.sa = gpd.GeoDataFrame(geometry=[self.aoi], crs=4326); self.grid = make_master_grid(self.sa.to_crs(32644).total_bounds)
        fp = lambda y0, y1: json.dumps(mapping(box(80.0, y0, 80.5, y1)))   # noqa: E731
        cov, inv = [], []
        for d in DATES8:
            ids = [f"S1A_IW_GRDH_1SDV_{d.replace('-', '')}T003147_{d.replace('-', '')}T003212_040589_04D094_AAAA", f"S1A_IW_GRDH_1SDV_{d.replace('-', '')}T003212_{d.replace('-', '')}T003237_040589_04D094_BBBB"]
            cov.append({"date_utc": d, "slice_ids": ";".join(ids)}); inv += [{"id": ids[0], "footprint": fp(13.03, 13.2)}, {"id": ids[1], "footprint": fp(12.9, 13.03)}]
        pd.DataFrame(cov).to_csv(tmp / "cov.csv", index=False); pd.DataFrame(inv).to_csv(tmp / "inv.csv", index=False)
        from src.utils import paths as P, status as S
        self.P, self.S = P, S; self.saved = (P.OUT_TAB, P.OUT_REP, P.OUT_FIG, P.DATA_PROC, S.STATUS_FILE)
        P.OUT_TAB, P.OUT_REP, P.OUT_FIG, P.DATA_PROC, S.STATUS_FILE = tmp / "t", tmp / "r", tmp / "f", tmp / "p", tmp / "status.json"
        self.calls = []; self.failing = set()
        stub = types.ModuleType("ee"); stub.Geometry = lambda *a, **k: None
        self.patches = [mock.patch.dict(sys.modules, {"ee": stub}), mock.patch.object(s, "load_study_area", lambda: (self.sa, self.sa, {"kind": "synthetic"})), mock.patch.object(s, "master_grid", lambda: self.grid),
                        mock.patch.object(s, "OUTDIR_DEFAULT", tmp / "p" / "s1_2021"), mock.patch.object(s, "INV_CSV", tmp / "inv.csv"), mock.patch.dict(s.CFG, {"coverage_csv": str(tmp / "cov.csv")}),
                        mock.patch.object(s, "make_exporter", self.factory), mock.patch.object(s, "paths", P)]
        for p in self.patches: p.start()
        from src.flood_detection import gee_sentinel1 as g1
        self.patches.append(mock.patch.object(g1, "init_ee", lambda *a, **k: None)); self.patches[-1].start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.P.OUT_TAB, self.P.OUT_REP, self.P.OUT_FIG, self.P.DATA_PROC, self.S.STATUS_FILE = self.saved

    def factory(self, ee, ctx):
        s, rng = self.s, np.random.default_rng(5)
        def exp(date):
            self.calls.append(date)
            if date in self.failing: raise RuntimeError("simulated EE failure")
            files = []
            for pol in pp.POLS:
                db = rng.normal(-12 if pol == "VV" else -19, 2, self.grid.shape); files += s.write_outputs(ctx["outdir"], date, pol, db, np.ones(self.grid.shape), self.grid, s.CFG)
            md = {k: "x" for k in pp.REQUIRED_META}
            md.update({"date_utc": date, "source_scene_ids": ctx["plan"][date], "pols_present": ["VV", "VH"], "status": "EXPORTED (QA pending)", "pol_plan": {}, "files": files,
                       "run_signature": ctx["sigs"][date], "source_stats_10m": {p: {"mean_linear": float(np.mean(10 ** (rng.normal(-12 if p == 'VV' else -19, 2, 20000) / 10)))} for p in pp.POLS},
                       "speckle_options": {}, "overlap_diagnostics": {}})
            mn = f"S1A_IW_D092_{date.replace('-', '')}_meta.json"; (ctx["outdir"] / mn).write_text(json.dumps(md)); return {"files": files + [mn], "meta_file": mn}
        return exp

    def run_main(self, *args):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["x", *args]), contextlib.redirect_stdout(buf): self.s.main()
        return buf.getvalue()

    def report(self): return (self.P.OUT_REP / "s1_2021_preprocessing_report.md").read_text(encoding="utf-8")

    def meta(self, d): return json.loads((self.P.DATA_PROC / "s1_2021" / f"S1A_IW_D092_{d.replace('-', '')}_meta.json").read_text())

    def test_single_date_run_does_not_claim_completion_and_states_agree(self):
        out = self.run_main("--dates", "2021-11-16"); rep = self.report()
        self.assertIn("1 of 1", out); self.assertIn("NOT COMPLETE", out); self.assertIn("overall M4C: 1 of 8", out)
        self.assertIn("1 of 1", rep); self.assertIn("1 of 8", rep); self.assertIn("Overall status: **NOT COMPLETE**", rep)
        self.assertNotIn("Overall status: **COMPLETE**", rep); self.assertNotIn("Milestone status: COMPLETE", rep)
        qa = pd.read_csv(self.P.OUT_TAB / "s1_2021_preprocessing_qa.csv")
        self.assertEqual(set(qa.date_status), {"QA_PASS"}); self.assertEqual(set(qa.date_utc), {"2021-11-16"})
        md = self.meta("2021-11-16"); st = pp.load_state(self.P.DATA_PROC / "s1_2021" / "preprocess_state.json")["2021-11-16"]
        self.assertEqual((md["status"], st["status"]), ("QA_PASS", "QA_PASS")); self.assertEqual(md["export_status"], "EXPORTED (QA pending)")       # all four agree
        self.assertEqual(json.loads(self.S.STATUS_FILE.read_text())["modules"]["S1PP"]["state"], "PARTIALLY COMPLETED")

    def test_rerun_is_stable_rasters_untouched_no_reexport(self):
        self.run_main("--dates", "2021-11-16"); out = self.P.DATA_PROC / "s1_2021"
        h = {p.name: pp.sha256_file(p) for p in out.glob("*.tif")}; self.calls.clear()
        self.run_main("--dates", "2021-11-16"); self.run_main("--qa-only", "--dates", "2021-11-16")
        self.assertEqual(self.calls, []); self.assertEqual(h, {p.name: pp.sha256_file(p) for p in out.glob("*.tif")}); self.assertEqual(self.meta("2021-11-16")["status"], "QA_PASS")

    def test_second_date_keeps_first_and_only_eight_passes_complete(self):
        self.run_main("--dates", "2021-11-16"); self.failing = {"2021-09-17"}
        self.run_main("--all"); self.assertNotIn("2021-11-16", self.calls[1:])                                         # up-to-date date skipped
        rep = self.report(); self.assertIn("Overall status: **NOT COMPLETE**", rep); self.assertIn("2021-09-17", rep.split("not yet QA_PASS:")[1].split("\n")[0])
        qa = pd.read_csv(self.P.OUT_TAB / "s1_2021_preprocessing_qa.csv"); self.assertEqual(len(set(qa.date_utc)), 8)
        self.failing = set(); out = self.run_main("--all"); rep = self.report()
        self.assertIn("overall M4C: 8 of 8", out); self.assertIn("-> COMPLETE", out); self.assertIn("Overall status: **COMPLETE**", rep)
        self.assertEqual(json.loads(self.S.STATUS_FILE.read_text())["modules"]["S1PP"]["state"], "COMPLETED")
        qa = pd.read_csv(self.P.OUT_TAB / "s1_2021_preprocessing_qa.csv"); self.assertEqual(set(qa.date_status), {"QA_PASS"})
        for d in DATES8: self.assertEqual(self.meta(d)["status"], "QA_PASS")


class TestHighValueDiagnostics(unittest.TestCase):
    def setUp(self):
        self.db = np.full(GRID.shape, -12.0); self.valid = np.ones(GRID.shape, bool); self.inside = np.ones(GRID.shape, bool)
        self.db[1:3, 1:3] = 9.0                    # component A: 4 cells
        self.db[8, 8] = 7.0; self.db[8, 9] = 7.0; self.db[9, 10] = 7.0        # B: 3 cells (diagonal link = 8-neighbour)
        self.db[7, 7] = 5.0                      # exactly the threshold: NOT above
        self.db[13, 13] = 20.0; self.valid[13, 13] = False       # invalid cell: excluded

    def test_counts_components_and_no_mutation(self):
        orig = self.db.copy(); s, comps, blocks, lab = pp.high_value_diagnostics(self.db, self.valid, self.inside, GRID, 5.0)
        np.testing.assert_array_equal(self.db, orig)                                                                       # input never modified
        self.assertEqual(s["high_cells"], 7); self.assertEqual(s["n_components"], 2); self.assertEqual(sorted(c["cells"] for c in comps), [3, 4])
        self.assertAlmostEqual(s["pct_of_aoi_cells"], round(100 * 7 / self.inside.sum(), 4)); self.assertEqual(s["largest_component_cells"], 4)
        self.assertEqual(sum(b["high_cells"] for b in blocks), 7)                                                          # block table accounts for every flagged cell
        self.assertEqual(s["size_histogram"]["2-4"], 2); self.assertEqual(s["cells_in_components_of_1"], 0)
        self.assertAlmostEqual(next(c for c in comps if c["cells"] == 4)["area_km2"], 4 * 900 / 1e6)

    def test_inside_mask_and_other_pol(self):
        ins = self.inside.copy(); ins[1:3, 1:3] = False; other = np.full(GRID.shape, -20.0); other[8, 8] = -8.0
        s, comps, _, _ = pp.high_value_diagnostics(self.db, self.valid, ins, GRID, 5.0, other_db=other)
        self.assertEqual(s["high_cells"], 3); self.assertAlmostEqual(s["other_pol_mean_db_at_high_cells"], (-8.0 - 20.0 - 20.0) / 3); self.assertAlmostEqual(s["other_pol_mean_db_elsewhere"], -20.0)

    def test_exceedance_table_monotonic_and_none_when_empty(self):
        t = pp.exceedance_table(self.db, self.valid, self.inside, (0.0, 5.0, 8.0, 10.0)); c = [r["cells"] for r in t]
        self.assertEqual(c, sorted(c, reverse=True)); self.assertEqual(c[1], 7); self.assertEqual(c[2], 4)
        s, comps, blocks, _ = pp.high_value_diagnostics(np.full(GRID.shape, -12.0), self.valid, self.inside, GRID, 5.0); self.assertEqual((s["high_cells"], s["n_components"], comps), (0, 0, []))

    def test_class_enrichment(self):
        cls = np.full(GRID.shape, 40); cls[0:7, 0:7] = 50; mask = (self.db > 5.0)
        r = {x["class"]: x for x in pp.class_enrichment(mask, cls, self.valid & self.inside)}
        self.assertEqual(r[50]["flagged_cells"] + r[40]["flagged_cells"], int((mask & self.valid).sum())); self.assertGreater(r[50]["enrichment_ratio"], 1.0); self.assertEqual(r[50]["name"], "built-up")

    def test_diagnostics_script_is_read_only(self):
        s = (ROOT / "scripts" / "s1_preprocess_diagnostics.py").read_text(encoding="utf-8")
        for bad in ("write_raster", "np.clip", "rasterio.open(p, \"w\"", "unlink", "os.remove"): self.assertNotIn(bad, s)
        self.assertIn("sha256_file(p) for k, p in prod.items()", s); self.assertIn("--ee-native-tail", s); self.assertIn("not overwritten", s)


class TestOverlapReconciliation(unittest.TestCase):
    def test_slice_time_relation(self):
        r = pp.slice_time_relation(ID_A, ID_B); self.assertEqual(r["gap_s"], 0.0); self.assertTrue(r["same_datatake"])
        self.assertEqual(pp.slice_time_relation(ID_B, ID_A), r)                                                           # order independent
        far = ID_B.replace("20211116T003212_20211116T003237", "20211116T003312_20211116T003337"); self.assertEqual(pp.slice_time_relation(ID_A, far)["gap_s"], 60.0)
        self.assertFalse(pp.slice_time_relation(ID_A, ID_B.replace("040589", "040590"))["same_datatake"])
        with self.assertRaises(ValueError): pp.parse_s1_id("not_a_scene")

    def _geoms(self, overlap_m):
        import geopandas as gpd
        x0, y0, x1, y1 = GRID.bounds; ym = (y0 + y1) / 2
        W = lambda g: gpd.GeoSeries([g], crs=GRID.crs).to_crs(4326).iloc[0]   # noqa: E731
        a = W(box(x0 - 500, ym - overlap_m / 2, x1 + 500, y1 + 500)); b = W(box(x0 - 500, y0 - 500, x1 + 500, ym + overlap_m / 2)); return a, b, W(box(x0, y0, x1, y1))

    def test_footprint_overlap_width_vs_pixel_size(self):
        a, b, aoi = self._geoms(4.0); o = pp.footprint_overlap_geometry(a, b, aoi)
        self.assertAlmostEqual(o["overlap_width_m"], 4.0, delta=0.05); self.assertGreater(o["overlap_length_m"], 100.0); self.assertLess(o["overlap_width_m"], 10.0)        # sub-pixel sliver
        a, b, aoi = self._geoms(60.0); self.assertAlmostEqual(pp.footprint_overlap_geometry(a, b, aoi)["overlap_width_m"], 60.0, delta=0.05)
        a, b, aoi = self._geoms(0.0); self.assertLess(pp.footprint_overlap_geometry(a, b, aoi)["overlap_area_m2"], 1.0)                                                        # abutting outlines
        self.assertEqual(pp.overlap_diff_stats(np.full((2, 2), np.nan), np.full((2, 2), -9.0))["n_overlap_px"], 0)                                                            # outline overlap != valid pixel overlap
