"""Rainfall tests (V2.3 / M3). SYNTHETIC rasters only: they test handling rules (missing days, coverage, units, dates, alignment),
not any real rainfall. No 2015 or 2023 rainfall values are used or implied."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import importlib.util
import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import box
import geopandas as gpd
from src.geospatial import rainfall as R
from src.utils import status

T = from_origin(80.0, 13.3, 0.05, 0.05)       # 10 x 12 native cells covering lon 80.0-80.5, lat 12.7-13.3
AOI = box(80.15, 12.90, 80.30, 13.15)


class TestLibrary(unittest.TestCase):
    def test_date_ranges(self):
        d = R.daterange("2015-11-08", "2015-12-05")
        self.assertEqual((len(d), d[0], d[-1]), (28, date(2015, 11, 8), date(2015, 12, 5)))
        self.assertEqual(len(R.daterange("2015-12-31", "2016-01-02")), 3)
        self.assertEqual(R.daterange("2015-12-05", "2015-11-08"), [])
        self.assertEqual(len(R.daterange("2016-02-28", "2016-03-01")), 3)          # leap day
        self.assertEqual(R.missing_dates(d, d[:5] + d[7:]), [d[5], d[6]])

    def test_missing_day_never_zero(self):
        a = np.full((3, 3), 10.0)
        tot, nv = R.strict_total([a, None, a])
        self.assertTrue(np.isnan(tot).all() and (nv == 2).all())                    # NOT 20
        tot2, nv2 = R.strict_total([a, a, a]); self.assertTrue((tot2 == 30).all())
        lb, nvl = R.strict_total([a, None, a], allow_partial=True)
        self.assertTrue((lb == 20).all() and (nvl == 2).all())                      # lower bound only when explicitly asked
        b = a.copy(); b[0, 0] = np.nan                                             # one invalid cell on one day
        t3, _ = R.strict_total([a, b, a]); self.assertTrue(np.isnan(t3[0, 0]) and t3[1, 1] == 30)
        with self.assertRaises(ValueError): R.strict_total([None, None])

    def test_clean_day_never_creates_zero(self):
        raw = np.array([[-9999.0, -1.0, 0.0], [5.0, 2000.0, np.nan]])
        mm, c = R.clean_day(raw, "mm", nodata=-9999.0)
        self.assertTrue(np.isnan(mm[0, 0]) and np.isnan(mm[0, 1]) and np.isnan(mm[1, 1]) and np.isnan(mm[1, 2]))
        self.assertEqual((mm[0, 2], mm[1, 0]), (0.0, 5.0))                          # genuine zero preserved, distinct from missing
        self.assertEqual((c["nodata_cells"], c["negative_cells"], c["over_range_cells"]), (2, 1, 1))

    def test_unit_conversion(self):
        self.assertEqual(float(R.to_mm(0.25, "m")), 250.0)
        self.assertEqual(float(R.to_mm(12.0, "kg m-2")), 12.0)
        self.assertEqual(float(R.to_mm(2.0, "cm")), 20.0)
        self.assertEqual(float(R.to_mm(3.0, "mm/h", hours=24)), 72.0)
        with self.assertRaises(ValueError): R.to_mm(1.0, "mm/h")                    # rate without period
        with self.assertRaises(ValueError): R.to_mm(1.0, "inches")                  # unknown unit: no silent default

    def test_weights_and_coverage(self):
        w = R.cell_weights(T, (12, 10), AOI)
        self.assertAlmostEqual(float(w.sum()), 1.0, delta=0.03)
        half = R.cell_weights(T, (12, 10), box(80.40, 12.90, 80.60, 13.15))          # AOI half outside the raster
        self.assertAlmostEqual(float(half.sum()), 0.5, delta=0.03)
        mm = np.full((12, 10), 5.0)
        self.assertEqual(R.classify_day(mm, w), "OK")
        self.assertEqual(R.classify_day(None, w), "MISSING")
        part = mm.copy(); part[:, :5] = np.nan                                        # western half of the AOI cells invalid
        self.assertEqual(R.classify_day(part, w), "INCOMPLETE_COVERAGE")
        st = R.weighted_stats(part, w); self.assertLess(st["coverage"], 0.95)
        self.assertEqual(R.weighted_stats(np.full((12, 10), np.nan), w)["cells_valid"], 0)
        self.assertEqual(R.classify_day(mm, half), "INCOMPLETE_COVERAGE")             # raster does not cover the whole AOI

    def test_weighted_mean(self):
        w = np.zeros((2, 2)); w[0, 0], w[0, 1] = 0.75, 0.25
        mm = np.array([[10.0, 30.0], [999.0, 999.0]])
        self.assertAlmostEqual(R.weighted_stats(mm, w)["mean_mm"], 15.0)

    def test_alignment(self):
        g = (T, (12, 10), CRS.from_epsg(4326))
        self.assertTrue(R.check_same_grid([g, g]))
        with self.assertRaises(ValueError): R.check_same_grid([g, (T, (12, 11), CRS.from_epsg(4326))])
        with self.assertRaises(ValueError): R.check_same_grid([g, (from_origin(80.01, 13.3, 0.05, 0.05), (12, 10), CRS.from_epsg(4326))])
        with self.assertRaises(ValueError): R.check_same_grid([g, (T, (12, 10), CRS.from_epsg(32644))])

    def test_window_total_and_k_day(self):
        a = np.ones((2, 2)); dm = {date(2015, 12, d): a * d for d in range(1, 11)}
        t, miss = R.window_total(dm, date(2015, 12, 6), 3)                            # days 3,4,5 (reference day excluded)
        self.assertEqual((miss, float(t[0, 0])), ([], 12.0))
        t, miss = R.window_total(dm, date(2015, 12, 6), 3, include_end_day=True); self.assertEqual(float(t[0, 0]), 15.0)
        dm[date(2015, 12, 4)] = None
        t, miss = R.window_total(dm, date(2015, 12, 6), 3); self.assertIsNone(t); self.assertEqual(miss, [date(2015, 12, 4)])
        mx, used, skipped = R.max_k_day(dm, sorted(dm), 3)
        self.assertEqual((used, skipped), (5, 3)); self.assertEqual(float(mx[0, 0]), 27.0)  # windows containing day 4 skipped

    def test_comparability_and_anomaly(self):
        a = {"source_id": "x", "version": "1", "native_resolution": "0.05 deg", "day_definition": "UTC day", "product_type": "sat"}
        self.assertTrue(R.comparable(a, dict(a))[0])
        ok, why = R.comparable(a, dict(a, source_id="y", native_resolution="0.25 deg")); self.assertFalse(ok); self.assertEqual(len(why), 2)
        self.assertFalse(R.comparable(dict(a, day_definition="UNCONFIRMED"), a)[0])
        clim = np.stack([np.full((2, 2), float(v)) for v in range(1, 13)])
        an = R.anomaly(np.full((2, 2), 6.0), clim, min_years=10)
        self.assertAlmostEqual(float(an["clim_mean_mm"][0, 0]), 6.5); self.assertAlmostEqual(float(an["percentile_rank"][0, 0]), 0.5)
        short = R.anomaly(np.full((2, 2), 6.0), clim[:5], min_years=10); self.assertTrue(np.isnan(short["diff_mm"]).all())


def load_script():
    spec = importlib.util.spec_from_file_location("rain_wf", ROOT / "scripts" / "rainfall_workflow.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


SRC = {"source_id": "synthetic", "name": "SYNTHETIC test source", "version": "0", "product_type": "satellite-blended", "unit": "mm",
       "day_definition": "UTC calendar day", "file_pattern": "{date:%Y%m%d}.tif", "expected_crs": "EPSG:4326", "nodata": -9999.0,
       "native_resolution": "0.05 deg", "obtained_from": "synthetic", "obtained_on": "2026-01-01", "licence_note": "n/a"}


class TestWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()
        cls.ctx = R.daterange(*json.loads((ROOT / "config" / "rainfall_events.json").read_text())["events"]["2015_nov_dec"]["context_window"])

    def make(self, d, skip=(), value=1.0, unit_scale=1.0, epsg=4326, shift=0.0, half_nan=(), src=None):
        inp = Path(d) / "in"; inp.mkdir()
        tr = from_origin(80.0 + shift, 13.3, 0.05, 0.05)
        for day in self.ctx:
            if day in skip:
                continue
            arr = np.full((12, 10), value * unit_scale, dtype="float32")
            if day in half_nan:
                arr[:, :5] = -9999.0
            with rasterio.open(inp / f"{day:%Y%m%d}.tif", "w", driver="GTiff", height=12, width=10, count=1, dtype="float32",
                               crs=CRS.from_epsg(epsg), transform=tr, nodata=-9999.0) as ds:
                ds.write(arr, 1)
        if src is not False:
            (inp / "source.json").write_text(json.dumps(src or SRC))
        return inp

    def run_wf(self, d, inp, *extra):
        sa = gpd.GeoDataFrame(geometry=[AOI], crs=4326)
        old_f, old_a = status.STATUS_FILE, sys.argv
        status.STATUS_FILE = Path(d) / "status.json"
        sys.argv = ["x", "--source-id", "synthetic", "--input-dir", str(inp), "--out-dir", str(Path(d) / "proc"), "--outputs-dir", str(Path(d) / "out"), *extra]
        try:
            with mock.patch("src.geospatial.study_area.load_study_area", return_value=(sa, sa, {})), \
                 mock.patch("src.geospatial.study_area.bounds_wgs84", return_value=(80.15, 12.9, 80.30, 13.15)):
                self.mod.main()
        finally:
            status.STATUS_FILE, sys.argv = old_f, old_a
        return json.loads((Path(d) / "status.json").read_text())["modules"]["C2"]

    def test_complete_run_native_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            st = self.run_wf(d, self.make(d))
            self.assertEqual(st["state"], "COMPLETED", st["message"])
            tif = Path(d) / "proc" / "synthetic" / "2015_nov_dec_event_total_mm_native.tif"
            with rasterio.open(tif) as ds:
                a = ds.read(1)
                self.assertEqual(abs(ds.res[0]), 0.05)                                  # native resolution preserved (not 30 m)
                self.assertTrue(ds.crs.to_epsg() == 4326)
                self.assertTrue((a[a != -9999.0] == 28.0).all())                         # 28 days x 1 mm
            self.assertFalse(list((Path(d) / "proc").rglob("*30m*")))                    # no resampled product unless requested
            ts = pd.read_csv(Path(d) / "out" / "tables" / "rainfall_synthetic_2015_nov_dec_daily_series.csv")
            self.assertEqual(len(ts), 153); self.assertTrue((ts["status"] == "OK").all())

    def test_missing_days_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            miss = {date(2015, 11, 20), date(2015, 11, 21)}
            st = self.run_wf(d, self.make(d, skip=miss))
            self.assertEqual(st["state"], "PARTIALLY COMPLETED")
            self.assertFalse((Path(d) / "proc" / "synthetic" / "2015_nov_dec_event_total_mm_native.tif").exists())   # no total at all
            ts = pd.read_csv(Path(d) / "out" / "tables" / "rainfall_synthetic_2015_nov_dec_daily_series.csv")
            m = ts[ts["date"].isin(["2015-11-20", "2015-11-21"])]
            self.assertTrue((m["status"] == "MISSING").all()); self.assertTrue(m["aoi_mean_mm"].isna().all())         # blank, not 0
            self.assertIn("NOT COMPUTED", (Path(d) / "out" / "reports" / "rainfall_synthetic_2015_nov_dec_report.md").read_text())
            ante = pd.read_csv(Path(d) / "out" / "tables" / "rainfall_synthetic_2015_nov_dec_antecedent_before_s1.csv")
            row = ante[ante["s1_date"] == "2015-11-24"].iloc[0]
            self.assertTrue(pd.isna(row["prior_7d_aoi_mean_mm"])); self.assertEqual(int(row["prior_7d_missing_days"]), 2)  # window with a gap -> no number
            self.assertAlmostEqual(float(row["prior_1d_aoi_mean_mm"]), 1.0, places=2)                                    # 23 Nov complete

    def test_allow_partial_is_labelled_lower_bound(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_wf(d, self.make(d, skip={date(2015, 11, 20)}), "--allow-partial")
            files = list((Path(d) / "proc" / "synthetic").glob("*.tif"))
            lb = [f for f in files if "LOWER_BOUND" in f.name]
            self.assertEqual(len(lb), 1); self.assertFalse(any(f.name.endswith("event_total_mm_native.tif") for f in files))
            with rasterio.open(lb[0]) as ds:
                a = ds.read(1); self.assertTrue((a[a != -9999.0] == 27.0).all()); self.assertIn("LOWER BOUND", ds.descriptions[0])

    def test_incomplete_coverage_day_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            st = self.run_wf(d, self.make(d, half_nan={date(2015, 11, 25)}))
            ts = pd.read_csv(Path(d) / "out" / "tables" / "rainfall_synthetic_2015_nov_dec_daily_series.csv")
            self.assertEqual(ts[ts["date"] == "2015-11-25"]["status"].iloc[0], "INCOMPLETE_COVERAGE")
            self.assertEqual(st["state"], "PARTIALLY COMPLETED")
            self.assertFalse((Path(d) / "proc" / "synthetic" / "2015_nov_dec_event_total_mm_native.tif").exists())

    def test_unit_conversion_in_workflow(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_wf(d, self.make(d, value=1.0, unit_scale=0.001, src=dict(SRC, unit="m")))     # files in metres
            with rasterio.open(Path(d) / "proc" / "synthetic" / "2015_nov_dec_event_total_mm_native.tif") as ds:
                a = ds.read(1); self.assertTrue(np.allclose(a[a != -9999.0], 28.0, atol=1e-3))

    def test_resample_is_labelled(self):
        with tempfile.TemporaryDirectory() as d:
            from src.geospatial.grid import make_master_grid
            g = make_master_grid((400000, 1430000, 400300, 1430300), pad_cells=0)
            with mock.patch("src.geospatial.study_area.master_grid", return_value=g):
                self.run_wf(d, self.make(d), "--resample-to-master")
            rs = list((Path(d) / "proc" / "synthetic").glob("*RESAMPLED*"))
            self.assertEqual(len(rs), 1)
            with rasterio.open(rs[0]) as ds:
                self.assertIn("NO 30 m information", ds.descriptions[0]); self.assertEqual(ds.res, (30.0, 30.0))

    def test_blocked_paths(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_wf(d, self.make(d, src=False))["state"], "BLOCKED")            # no source.json
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_wf(d, self.make(d, src=dict(SRC, unit="furlongs")))["state"], "BLOCKED")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_wf(d, self.make(d, src=dict(SRC, day_definition="FILL_ME")))["state"], "BLOCKED")
        with tempfile.TemporaryDirectory() as d:
            st = self.run_wf(d, self.make(d, epsg=4269)); self.assertEqual(st["state"], "BLOCKED"); self.assertIn("CRS", st["message"])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_wf(d, self.make(d, skip=set(self.ctx)))["state"], "BLOCKED")    # nothing readable

    def test_context_window_supports_30_day_antecedent_before_20_aug(self):
        ev = json.loads((ROOT / "config" / "rainfall_events.json").read_text())["events"]["2015_nov_dec"]
        self.assertEqual(ev["context_window"], ["2015-07-21", "2015-12-20"]); self.assertEqual(ev["event_window_label"], "PROVISIONAL")
        dm = {d: np.ones((2, 2)) for d in self.ctx}
        t, miss = R.window_total(dm, date(2015, 8, 20), 30)
        self.assertEqual(miss, []); self.assertEqual(float(t[0, 0]), 30.0)                   # 21 Jul .. 19 Aug inclusive, 20 Aug excluded
        dm2 = {d: v for d, v in dm.items() if d >= date(2015, 8, 1)}                          # the OLD 1 Aug start
        self.assertIsNotNone(R.window_total(dm2, date(2015, 8, 20), 30)[1] or None)           # old window had missing days
        self.assertEqual(len(R.window_total(dm2, date(2015, 8, 20), 30)[1]), 11)
        last = date(2015, 12, 20); self.assertEqual(self.ctx[-1], last)

    def test_provisional_day_definition_downgrades(self):
        with tempfile.TemporaryDirectory() as d:
            st = self.run_wf(d, self.make(d, src=dict(SRC, day_definition="PROVISIONAL: 24 h ending 08:30 IST")))
            self.assertEqual(st["state"], "PARTIALLY COMPLETED")
            for f in ("timeseries.png", "wettest_day_native.png"):
                self.assertTrue((Path(d) / "out" / "figures" / f"rainfall_synthetic_2015_nov_dec_{f}").exists())

    def test_unconfirmed_day_definition_downgrades(self):
        with tempfile.TemporaryDirectory() as d:
            st = self.run_wf(d, self.make(d, src=dict(SRC, day_definition="UNCONFIRMED")))
            self.assertEqual(st["state"], "PARTIALLY COMPLETED")


    def test_2021_sentinel1_dates_use_preprocessing_config_as_unassigned(self):
        events = json.loads((ROOT / "config" / "rainfall_events.json").read_text(encoding="utf-8"))["events"]
        observations, label, source = self.mod.load_s1_observations(events["2021_sep_nov"])
        expected = json.loads((ROOT / "config" / "s1_preprocess.json").read_text(encoding="utf-8"))["dates"]
        self.assertEqual(source, "s1_preprocess.json")
        self.assertEqual(label, "Sentinel-1 processed-observation date")
        self.assertEqual([item["date"] for item in observations], expected)
        self.assertEqual(len(observations), 8)
        self.assertTrue(all(item["category"] == "unassigned" for item in observations))
        self.assertTrue(all(item["kind"] == "processed-observation" for item in observations))
        self.assertFalse(any(item["date"].startswith("2015-") for item in observations))

    def test_2015_sentinel1_candidate_roles_are_preserved(self):
        events = json.loads((ROOT / "config" / "rainfall_events.json").read_text(encoding="utf-8"))["events"]
        observations, label, source = self.mod.load_s1_observations(events["2015_nov_dec"])
        configured = json.loads((ROOT / "config" / "s1_candidate_roles.json").read_text(encoding="utf-8"))["candidates"]
        self.assertEqual(source, "s1_candidate_roles.json")
        self.assertEqual(label, "Sentinel-1 candidate date")
        self.assertEqual(
            [(x["date"], x["category"]) for x in observations],
            [(x["date"], x["category"]) for x in configured],
        )
        self.assertEqual(len(observations), 8)

    def test_sentinel1_date_source_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            config_dir = Path(d)
            (config_dir / "s1_preprocess.json").write_text(json.dumps({"dates": ["2021-09-05", "2021-09-05"]}))
            with self.assertRaisesRegex(ValueError, "duplicate Sentinel-1 date"):
                self.mod.load_s1_observations({"sentinel1_dates_from": "config/s1_preprocess.json"}, config_dir)


class TestRegression(unittest.TestCase):
    def test_module_c_no_longer_zero_fills(self):
        txt = (ROOT / "scripts" / "process_rainfall.py").read_text()
        self.assertNotIn("nan_to_num(days", txt); self.assertNotIn("nan=0.0", txt)
        self.assertIn("strict_total", txt)

    def test_source_register_is_unconfirmed_and_has_no_download(self):
        c = json.loads((ROOT / "config" / "rainfall_sources.json").read_text())
        self.assertTrue(all(any(k in s["day_definition"] for k in ("UNCONFIRMED", "NOT VERIFIED")) for s in c["sources"]))      # nothing is registered as a verified day definition
        self.assertGreaterEqual(len(c["comparison_rules"]), 4)

if __name__ == "__main__":
    unittest.main()
