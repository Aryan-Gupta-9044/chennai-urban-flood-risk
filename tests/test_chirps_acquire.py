"""CHIRPS acquisition/preparation/comparison tests on SYNTHETIC rasters with simulated failures. The Earth Engine calls of scripts/fetch_chirps_rainfall.py are
NOT covered here (UNTESTED live); the acquisition engine, validation, preparation, workflow hand-off and comparison logic are."""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import rasterio
from rasterio.transform import Affine
from shapely.geometry import Polygon, box
from src.geospatial import chirps, chirps_acquire as CA, rainfall as R, rainfall_compare as RC
from src.utils import status

TR = Affine(0.05000000074505806, 0, -180.0, 0, -0.05000000074505806, 60.0)       # the live-verified Earth Engine grid
AOI = Polygon([(80.134, 12.9), (80.333, 12.852), (80.333, 13.235), (80.2, 13.235)])
WIN = chirps.snap_window(TR, AOI.bounds, 1); WTR = chirps.window_transform(TR, WIN); SHAPE = (WIN[3], WIN[2])
W, TOUCH = chirps.aoi_cell_weights(WTR, SHAPE, AOI)
CTX = R.daterange("2015-07-21", "2015-12-20")


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def rain(d, r, c): return 0.0 if (r + c + d.day) % 4 == 0 else float(1 + (r * 7 + c + d.day) % 9)


def write_raw(path, d, tr=WTR, shape=SHAPE, masked=(), zero_in_masked=False, crs="EPSG:4326"):
    H, Wd = shape; p = np.zeros((H, Wd), "float32"); v = np.ones((H, Wd), "float32")
    for r in range(H):
        for c in range(Wd): p[r, c] = rain(d, r, c)
    for (r, c) in masked:
        v[r, c] = 0; p[r, c] = 0.0 if zero_in_masked else chirps.EXPORT_NODATA
    with rasterio.open(path, "w", driver="GTiff", height=H, width=Wd, count=2, dtype="float32", crs=crs, transform=tr) as ds:
        ds.write(p, 1); ds.write(v, 2)


def validator(d, path): return CA.validate_raw(path, crs="EPSG:4326", native_tr=TR, win_tr=WTR, shape=SHAPE, weights=W, touch=TOUCH)


class TestAcquireEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.raw = Path(self.tmp.name) / "raw"; self.man = self.raw / "download_manifest.json"; self.raw.mkdir()
        self.calls = []; self.sleeps = []
    def tearDown(self): self.tmp.cleanup()

    def exporter(self, fail_first=0, bad_grid=(), bad_mask=(), boom=()):
        seen = {}
        def fn(d, tmp):
            self.calls.append(d); seen[d] = seen.get(d, 0) + 1
            if d in boom: raise RuntimeError("EEException: quota")
            if seen[d] <= fail_first: raise ConnectionError("reset by peer")
            if d in bad_grid: write_raw(tmp, d, tr=Affine(1.0, 0, 80.013, 0, -1.0, 13.97), shape=(2, 1))
            elif d in bad_mask: write_raw(tmp, d, masked=[(3, 3)], zero_in_masked=True)
            else: write_raw(tmp, d)
            return {"http_status": 200, "content_type": "image/tiff", "request_params": {"crs": "EPSG:4326"}, "url_host": "https://x/y"}
        return fn

    def run_acq(self, dates, fn, **kw):
        return CA.acquire(dates, self.raw, fn, validator, self.man, header={"dataset": chirps.DATASET_ID}, sleep=self.sleeps.append, log=lambda *_: None, **kw)

    def test_clean_download_records_provenance_and_checksums(self):
        ds = CTX[:3]; m = self.run_acq(ds, self.exporter())
        for d in ds:
            e = m["entries"][d.isoformat()]; f = self.raw / CA.raw_name(d)
            self.assertEqual(e["status"], "OK"); self.assertEqual(e["sha256"], CA.sha256_file(f)); self.assertEqual(e["http_status"], 200)
            self.assertEqual(e["validation"]["cells_touching_aoi"], int(TOUCH.sum())); self.assertGreater(e["validation"]["zero_cells_valid"], -1)
        self.assertEqual(CA.summarize(m, ds)["ok"], 3); json.loads(self.man.read_text())

    def test_retry_with_exponential_backoff_then_success(self):
        d = CTX[0]; m = self.run_acq([d], self.exporter(fail_first=2), retries=4, backoff=2.0)
        self.assertEqual(m["entries"][d.isoformat()]["status"], "OK"); self.assertEqual(self.sleeps, [2.0, 4.0])
        self.assertEqual([a["outcome"] for a in m["entries"][d.isoformat()]["attempts"]], ["error", "error", "ok"])

    def test_persistent_failure_is_missing_never_zero(self):
        d = CTX[1]; m = self.run_acq([d], self.exporter(boom={d}), retries=3)
        self.assertEqual(m["entries"][d.isoformat()]["status"], "FAILED"); self.assertFalse((self.raw / CA.raw_name(d)).exists())
        s = CA.summarize(m, [d]); self.assertEqual(s["failed_or_missing"], [d.isoformat()]); self.assertEqual(s["ok"], 0)
        self.assertEqual(list(self.raw.glob("*.tif")), [])                                   # no placeholder raster of any kind

    def test_wrong_grid_and_zero_filled_mask_are_rejected(self):
        a, b, c = CTX[:3]
        m = self.run_acq([a, b, c], self.exporter(bad_grid={a}, bad_mask={b}), retries=2)
        self.assertEqual(m["entries"][a.isoformat()]["status"], "FAILED"); self.assertEqual(m["entries"][b.isoformat()]["status"], "FAILED"); self.assertEqual(m["entries"][c.isoformat()]["status"], "OK")
        probs = json.dumps(m["entries"][a.isoformat()]["attempts"]); self.assertIn("pixel size", probs); self.assertIn("shape", probs)
        self.assertIn("masked cells hold a data value", json.dumps(m["entries"][b.isoformat()]["attempts"]))
        self.assertEqual(len(list((self.raw / "failed").glob("*.invalid"))), 4)              # rejected files are kept for inspection, outside raw/

    def test_resume_makes_no_new_calls_and_keeps_checksums(self):
        ds = CTX[:4]; m1 = self.run_acq(ds, self.exporter()); n = len(self.calls)
        m2 = self.run_acq(ds, self.exporter(boom=set(ds)))                                   # any download would raise
        self.assertEqual(len(self.calls), n)
        for d in ds:
            self.assertEqual(m2["entries"][d.isoformat()]["sha256"], m1["entries"][d.isoformat()]["sha256"]); self.assertIn("resumed", m2["entries"][d.isoformat()]["provenance"])

    def test_resume_after_partial_failure_only_fetches_missing(self):
        ds = CTX[:3]; self.run_acq(ds, self.exporter(boom={ds[1]}), retries=1); self.calls.clear()
        m = self.run_acq(ds, self.exporter()); self.assertEqual(self.calls, [ds[1]]); self.assertEqual(CA.summarize(m, ds)["ok"], 3)

    def test_corrupt_existing_file_is_quarantined_and_redownloaded(self):
        d = CTX[0]; (self.raw / CA.raw_name(d)).write_bytes(b"not a tiff")
        m = self.run_acq([d], self.exporter()); self.assertEqual(m["entries"][d.isoformat()]["status"], "OK"); self.assertEqual(len(list((self.raw / "failed").glob("*.invalid"))), 1)

    def test_valid_untracked_file_is_adopted_not_overwritten_unless_forced(self):
        d = CTX[0]; f = self.raw / CA.raw_name(d); write_raw(f, d); sha = CA.sha256_file(f)
        m = self.run_acq([d], self.exporter()); self.assertEqual(self.calls, []); self.assertIn("adopted", m["entries"][d.isoformat()]["provenance"]); self.assertEqual(CA.sha256_file(f), sha)
        self.run_acq([d], self.exporter(), force=True); self.assertEqual(self.calls, [d])

    def test_keyboard_interrupt_saves_manifest(self):
        ds = CTX[:3]
        def fn(d, tmp):
            if d == ds[1]: raise KeyboardInterrupt
            write_raw(tmp, d); return {}
        with self.assertRaises(KeyboardInterrupt): self.run_acq(ds, fn)
        m = CA.load_manifest(self.man); self.assertEqual(m["entries"][ds[0].isoformat()]["status"], "OK")

    def test_genuine_zero_is_valid_and_counted(self):
        d = CTX[0]; write_raw(self.raw / "t.tif", d)
        r = validator(d, self.raw / "t.tif"); self.assertEqual(r["problems"], []); self.assertGreater(r["zero_cells_valid"], 0); self.assertEqual(r["cells_missing"], 0)

    def test_masked_cell_inside_aoi_lowers_coverage_but_is_accepted_as_masked(self):
        d = CTX[0]; rr, cc = np.where(TOUCH); write_raw(self.raw / "t.tif", d, masked=[(rr[0], cc[0])])
        r = validator(d, self.raw / "t.tif"); self.assertEqual(r["problems"], []); self.assertEqual(r["cells_missing"], 1); self.assertLess(r["aoi_area_coverage"], 1.0)

    def test_non_geotiff_and_zip_download_bodies(self):
        with self.assertRaises(RuntimeError): CA.tif_bytes_from_download(b"<html>quota</html>")
        write_raw(self.raw / "t.tif", CTX[0]); raw = (self.raw / "t.tif").read_bytes()
        import io, zipfile
        b = io.BytesIO(); zipfile.ZipFile(b, "w").writestr("x.tif", raw); self.assertEqual(CA.tif_bytes_from_download(b.getvalue()), raw)

    def test_wrong_crs_rejected(self):
        write_raw(self.raw / "t.tif", CTX[0], crs="EPSG:3857"); self.assertTrue(any("CRS" in x for x in validator(CTX[0], self.raw / "t.tif")["problems"]))

    def _probe_files(self, d, window=("2015-07-21", "2015-12-20"), with_json_window=False, csv_dates=None):
        p = Path(d) / "reports" / "probe.json"; p.parent.mkdir(parents=True, exist_ok=True)
        n = len(R.daterange(*window))
        good = {"verdict": "PROCEED-TO-REVIEW", "temporal_completeness_verified": True, "crs": "EPSG:4326", "transform": list(TR)[:6], "cells_touching_aoi": int(TOUCH.sum()),
                "temporal_completeness": {"dates_meeting": n, "dates_expected": n}}
        if with_json_window: good["window"] = {"start": window[0], "end": window[1], "n_dates": n}
        p.write_text(json.dumps(good))
        t = Path(d) / "tables"; t.mkdir(exist_ok=True)
        ds = csv_dates if csv_dates is not None else R.daterange(*window)
        (t / "chirps_v3_sat_probe_dates.csv").write_text("date,in_collection\n" + "\n".join(f"{x.isoformat()},True" for x in ds) + "\n")
        return p, good

    def test_probe_gate(self):
        fetch = load("fetch_chirps_rainfall"); args = ("EPSG:4326", TR, int(TOUCH.sum()), "2015-07-21", "2015-12-20")
        with tempfile.TemporaryDirectory() as d:
            p, good = self._probe_files(d)                                                          # window recovered from the probe's per-date table (older probe JSON has none)
            self.assertEqual(fetch.gate_on_probe(p, *args), [])
            for k, v in (("verdict", "STOP"), ("cells_touching_aoi", 30), ("temporal_completeness_verified", False), ("crs", "EPSG:3857")):
                p.write_text(json.dumps({**good, k: v})); self.assertTrue(fetch.gate_on_probe(p, *args), k)
            p.write_text(json.dumps({**good, "temporal_completeness": {"dates_meeting": 150, "dates_expected": 153}})); self.assertTrue(fetch.gate_on_probe(p, *args))
            self.assertTrue(fetch.gate_on_probe(Path(d) / "none.json", *args))

    def test_gate_rejects_a_different_window_with_the_same_number_of_dates(self):
        fetch = load("fetch_chirps_rainfall")
        with tempfile.TemporaryDirectory() as d:
            p, _ = self._probe_files(d, window=("2015-07-22", "2015-12-21"))                         # 153 dates, shifted by ONE day
            probs = fetch.gate_on_probe(p, "EPSG:4326", TR, int(TOUCH.sum()), "2015-07-21", "2015-12-20")
            self.assertTrue(any("probe window 2015-07-22..2015-12-21" in x and "!= requested 2015-07-21..2015-12-20" in x for x in probs), probs)
            p2, _ = self._probe_files(d, window=("2015-07-21", "2015-12-20"), with_json_window=True)   # exact window -> accepted (JSON window preferred)
            self.assertEqual(fetch.gate_on_probe(p2, "EPSG:4326", TR, int(TOUCH.sum()), "2015-07-21", "2015-12-20"), [])
            self.assertTrue(fetch.gate_on_probe(p2, "EPSG:4326", TR, int(TOUCH.sum()), "2015-07-21", "2015-12-19"))     # a narrower request is also rejected
            self.assertTrue(fetch.gate_on_probe(p2, "EPSG:4326", TR, int(TOUCH.sum()), "2015-07-20", "2015-12-20"))

    def test_gate_json_window_overrides_table_and_unknown_window_is_rejected(self):
        fetch = load("fetch_chirps_rainfall")
        with tempfile.TemporaryDirectory() as d:
            p, good = self._probe_files(d, with_json_window=True); j = json.loads(p.read_text()); j["window"]["end"] = "2015-12-19"; p.write_text(json.dumps(j))
            self.assertTrue(fetch.gate_on_probe(p, "EPSG:4326", TR, int(TOUCH.sum()), "2015-07-21", "2015-12-20"))      # JSON says ..19 although the table says ..20
        with tempfile.TemporaryDirectory() as d:
            p, _ = self._probe_files(d); (Path(d) / "tables" / "chirps_v3_sat_probe_dates.csv").unlink()
            self.assertTrue(any("probe window unknown" in x for x in fetch.gate_on_probe(p, "EPSG:4326", TR, int(TOUCH.sum()), "2015-07-21", "2015-12-20")))
        with tempfile.TemporaryDirectory() as d:
            gap = [x for x in CTX if x != date(2015, 9, 1)]; p, _ = self._probe_files(d, csv_dates=gap)
            self.assertTrue(any("contiguous" in x for x in fetch.gate_on_probe(p, "EPSG:4326", TR, int(TOUCH.sum()), "2015-07-21", "2015-12-20")))

    def test_probe_script_now_records_its_window(self):
        self.assertIn('"window": {"start": start, "end": end', (ROOT / "scripts" / "probe_chirps_coverage.py").read_text(encoding="utf-8"))


def low_coverage_mask(target_below=0.95):
    """Masked AOI cells (heaviest first) until the AOI-area coverage falls below target_below."""
    rr, cc = np.where(TOUCH); order = np.argsort(-W[rr, cc]); masked, lost = [], 0.0
    for k in order:
        masked.append((int(rr[k]), int(cc[k]))); lost += W[rr[k], cc[k]]
        if 1 - lost < target_below - 0.01: break
    return masked


class TestLowCoverage(unittest.TestCase):
    """A valid file below --min-coverage is LOW_COVERAGE: kept for inspection/resume, never accepted, and it blocks COMPLETE."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.raw = Path(self.tmp.name) / "raw"; self.raw.mkdir(); self.man = self.raw / "m.json"; self.low = low_coverage_mask(); self.calls = []
    def tearDown(self): self.tmp.cleanup()

    def exporter(self, low_dates=()):
        def fn(d, tmp):
            self.calls.append(d); write_raw(tmp, d, masked=self.low if d in low_dates else []); return {"http_status": 200, "content_type": "image/tiff", "request_params": {}, "url_host": "h"}
        return fn

    def acq(self, dates, fn, **kw): return CA.acquire(dates, self.raw, fn, validator, self.man, sleep=lambda *_: None, log=lambda *_: None, **kw)

    def test_low_coverage_file_is_retained_flagged_and_blocks_complete(self):
        ds = CTX[:3]; bad = ds[1]; m = self.acq(ds, self.exporter({bad}), min_coverage=0.95)
        e = m["entries"][bad.isoformat()]
        self.assertEqual(e["status"], "LOW_COVERAGE"); self.assertLess(e["validation"]["aoi_area_coverage"], 0.95)
        f = self.raw / CA.raw_name(bad); self.assertTrue(f.exists()); self.assertEqual(e["sha256"], CA.sha256_file(f))               # valid data retained, checksummed
        self.assertEqual(list((self.raw / "failed").glob("*")), [])                                                                     # not quarantined as invalid
        s = CA.summarize(m, ds, 0.95)
        self.assertEqual((s["ok"], s["low_coverage"], s["failed_or_missing"], s["complete"]), (2, [bad.isoformat()], [], False))
        all_ok = self.acq(CTX[3:5], self.exporter()); self.assertTrue(CA.summarize(all_ok, CTX[3:5], 0.95)["complete"])                 # control: full-coverage dates do complete

    def test_resume_keeps_low_coverage_without_redownload_and_threshold_is_explicit(self):
        d = CTX[0]; self.acq([d], self.exporter({d}), min_coverage=0.95); n = len(self.calls)
        m = self.acq([d], self.exporter({d}), min_coverage=0.95); self.assertEqual(len(self.calls), n); self.assertEqual(m["entries"][d.isoformat()]["status"], "LOW_COVERAGE")
        m = self.acq([d], self.exporter({d}), min_coverage=0.10)                                                                        # only an explicit lower threshold re-classifies it
        self.assertEqual(m["entries"][d.isoformat()]["status"], "OK"); self.assertEqual(m["min_coverage"], 0.10)

    def test_summarize_rechecks_recorded_coverage_and_missing_dates_block_complete(self):
        ds = CTX[:2]; m = self.acq(ds, self.exporter({ds[0]}), min_coverage=0.01)                                                       # accepted at a very low threshold ...
        self.assertTrue(CA.summarize(m, ds)["complete"]); self.assertFalse(CA.summarize(m, ds, 0.95)["complete"])                       # ... but not at 95 %
        self.assertFalse(CA.summarize(m, CTX[:3], 0.01)["complete"])                                                                     # a never-attempted date blocks COMPLETE too

    def test_fetch_script_uses_whole_window_summary_and_reports_low_coverage(self):
        src = (ROOT / "scripts" / "fetch_chirps_rainfall.py").read_text(encoding="utf-8")
        self.assertIn("CA.summarize(m, expected, a.min_coverage)", src); self.assertIn('full = summ["complete"]', src); self.assertIn("LOW_COVERAGE dates", src); self.assertIn("min_coverage=a.min_coverage", src)


class TestPrepareAndWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.prep = load("prepare_chirps_rainfall"); cls.wf = load("rainfall_workflow")

    def build(self, d, dates=CTX, bad=()):
        base = Path(d) / "chirps"; raw = base / "raw"; raw.mkdir(parents=True)
        man = {"dataset": chirps.DATASET_ID, "crs": "EPSG:4326", "retrieval_started_utc": "2026-11-23T00:00:00+00:00", "entries": {}}
        rr, cc = np.where(TOUCH)
        for dd in dates:
            f = raw / CA.raw_name(dd); write_raw(f, dd, masked=[(0, 0)])                   # corner cell outside the AOI is masked
            man["entries"][dd.isoformat()] = {"date": dd.isoformat(), "status": "OK", "sha256": CA.sha256_file(f), "file": f.name}
        for dd in bad: man["entries"][dd.isoformat()] = {"date": dd.isoformat(), "status": "FAILED", "last_error": "quota"}; (raw / CA.raw_name(dd)).unlink(missing_ok=True)
        CA.save_manifest(raw / "download_manifest.json", man); return base

    def run_prep(self, d, base):
        old, oa = status.STATUS_FILE, sys.argv; status.STATUS_FILE = Path(d) / "status.json"
        sys.argv = ["x", "--base-dir", str(base), "--outputs-dir", str(Path(d) / "out")]
        try: rc = self.prep.main()
        finally: status.STATUS_FILE, sys.argv = old, oa
        return rc, json.loads((Path(d) / "status.json").read_text())["modules"]["CH3P"]

    def test_conversion_native_grid_nodata_and_zero_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            base = self.build(d, CTX[:5]); rc, st = self.run_prep(d, base)
            tifs = sorted((base / "daily").glob("*.tif")); self.assertEqual(len(tifs), 5); self.assertEqual(rc, 1)                       # 5 of 153: incomplete -> rc 1, not complete
            day = CTX[2]
            with rasterio.open(base / "daily" / f"{day:%Y%m%d}.tif") as a, rasterio.open(base / "raw" / CA.raw_name(day)) as b:
                x, y = a.read(1), b.read(1)
                self.assertEqual(a.transform, b.transform); self.assertEqual(a.crs, b.crs); self.assertEqual(a.nodata, -9999.0); self.assertEqual(a.shape, SHAPE)   # native, same georeferencing
                self.assertEqual(float(x[0, 0]), -9999.0)                                                                                 # masked -> nodata
                self.assertTrue(np.array_equal(x[1:, 1:] if False else x[b.read(2) == 1], y[b.read(2) == 1])); self.assertTrue(((x == 0) & (y == 0)).any())   # genuine zeros kept
            src = json.loads((base / "source.json").read_text())
            self.assertEqual(src["source_id"], "chirps_v3_daily"); self.assertIn("NOT VERIFIED", src["day_definition"]); self.assertEqual(src["nodata"], -9999.0)
            self.assertEqual(src["expected_crs"], "EPSG:4326"); self.assertIn("CC BY 4.0", src["licence_note"]); self.assertIn("doi", src); self.assertEqual(src["validation_status"], "NOT VALIDATED")
            self.assertIn("MISSING", (Path(d) / "out" / "tables" / "chirps_v3_sat_conversion.csv").read_text())

    def test_failed_and_tampered_dates_are_not_converted(self):
        with tempfile.TemporaryDirectory() as d:
            bad = CTX[1]; base = self.build(d, CTX[:4], bad=(bad,))
            tam = CTX[2]; f = base / "raw" / CA.raw_name(tam); write_raw(f, tam, masked=[(1, 1)])                                       # content changed after the manifest was written
            self.run_prep(d, base)
            names = {p.stem for p in (base / "daily").glob("*.tif")}
            self.assertNotIn(f"{bad:%Y%m%d}", names); self.assertNotIn(f"{tam:%Y%m%d}", names); self.assertIn(f"{CTX[0]:%Y%m%d}", names)
            txt = (Path(d) / "out" / "tables" / "chirps_v3_sat_conversion.csv").read_text(); self.assertIn("CHECKSUM_MISMATCH", txt)

    def test_no_manifest_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "chirps").mkdir(); rc, st = self.run_prep(d, Path(d) / "chirps"); self.assertEqual(rc, 2); self.assertEqual(st["state"], "BLOCKED")

    def test_workflow_on_full_prepared_window(self):
        import geopandas as gpd
        with tempfile.TemporaryDirectory() as d:
            base = self.build(d); rc, st = self.run_prep(d, base); self.assertEqual(rc, 0, st["message"]); self.assertEqual(len(list((base / "daily").glob("*.tif"))), 153)
            sa = gpd.GeoDataFrame(geometry=[AOI], crs=4326); old, oa = status.STATUS_FILE, sys.argv; status.STATUS_FILE = Path(d) / "s2.json"
            sys.argv = ["x", "--source-id", "chirps_v3_daily", "--input-dir", str(base), "--out-dir", str(Path(d) / "proc"), "--outputs-dir", str(Path(d) / "o2")]
            try:
                with mock.patch("src.geospatial.study_area.load_study_area", return_value=(sa, sa, {})), mock.patch("src.geospatial.study_area.bounds_wgs84", return_value=(80.0, 12.8, 80.45, 13.3)):
                    self.wf.main()
            finally: status.STATUS_FILE, sys.argv = old, oa
            s2 = json.loads((Path(d) / "s2.json").read_text())["modules"]["C2"]
            self.assertEqual(s2["state"], "PARTIALLY COMPLETED", s2["message"])                                                          # day definition provisional
            tot = Path(d) / "proc" / "chirps_v3_daily" / "2015_nov_dec_event_total_mm_native.tif"
            self.assertTrue(tot.exists())
            with rasterio.open(tot) as ds: self.assertAlmostEqual(ds.res[0], 0.05, places=6); self.assertEqual(ds.shape, SHAPE)         # native resolution preserved
            ser = (Path(d) / "o2" / "tables" / "rainfall_chirps_v3_daily_2015_nov_dec_daily_series.csv").read_text(); self.assertEqual(ser.count("MISSING"), 0)
            self.assertEqual(st["state"], "COMPLETED", st["message"])                                                                     # CH3P: all 153 converted -> not 'partial'
            rep = (Path(d) / "o2" / "reports" / "rainfall_chirps_v3_daily_2015_nov_dec_report.md").read_text(encoding="utf-8")
            self.assertNotIn("run marked partial", rep)
            self.assertIn("153 of 153", rep); self.assertIn("daily data are COMPLETE", rep)
            self.assertIn("solely because the day definition is provisional", rep); self.assertIn("NOT verified against IST", rep)     # caveat kept
            self.assertIn("any positive-area overlap", rep); self.assertIn("EXCLUDED", rep)

    def test_workflow_reports_missing_day_not_zero(self):
        import geopandas as gpd
        with tempfile.TemporaryDirectory() as d:
            miss = date(2015, 11, 20); base = self.build(d, [x for x in CTX if x != miss]); self.run_prep(d, base)
            sa = gpd.GeoDataFrame(geometry=[AOI], crs=4326); old, oa = status.STATUS_FILE, sys.argv; status.STATUS_FILE = Path(d) / "s2.json"
            sys.argv = ["x", "--source-id", "chirps_v3_daily", "--input-dir", str(base), "--out-dir", str(Path(d) / "proc"), "--outputs-dir", str(Path(d) / "o2")]
            try:
                with mock.patch("src.geospatial.study_area.load_study_area", return_value=(sa, sa, {})), mock.patch("src.geospatial.study_area.bounds_wgs84", return_value=(80.0, 12.8, 80.45, 13.3)):
                    self.wf.main()
            finally: status.STATUS_FILE, sys.argv = old, oa
            self.assertFalse((Path(d) / "proc" / "chirps_v3_daily" / "2015_nov_dec_event_total_mm_native.tif").exists())               # strict: no total with a missing day
            self.assertIn("NOT COMPUTED", (Path(d) / "o2" / "reports" / "rainfall_chirps_v3_daily_2015_nov_dec_report.md").read_text())


class TestPrepareCorrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.prep = load("prepare_chirps_rainfall")

    def build(self, d, dates, low=(), low_masked=None):
        base = Path(d) / "chirps"; raw = base / "raw"; raw.mkdir(parents=True); man = {"dataset": chirps.DATASET_ID, "crs": "EPSG:4326", "min_coverage": 0.95, "retrieval_started_utc": "2026-11-23T00:00:00+00:00", "entries": {}}
        for dd in dates:
            f = raw / CA.raw_name(dd); write_raw(f, dd, masked=low_masked if dd in low else [])
            res = validator(dd, f); man["entries"][dd.isoformat()] = {"date": dd.isoformat(), "status": CA.classify(res, 0.95), "sha256": CA.sha256_file(f), "file": f.name, "validation": res}
        CA.save_manifest(raw / "download_manifest.json", man); return base

    def run_prep(self, d, base, *extra):
        old, oa = status.STATUS_FILE, sys.argv; status.STATUS_FILE = Path(d) / "status.json"
        sys.argv = ["x", "--base-dir", str(base), "--outputs-dir", str(Path(d) / "out"), *extra]
        try: rc = self.prep.main()
        finally: status.STATUS_FILE, sys.argv = old, oa
        return rc

    def test_low_coverage_dates_are_not_silently_converted(self):
        with tempfile.TemporaryDirectory() as d:
            low = CTX[1]; base = self.build(d, CTX[:3], low=(low,), low_masked=low_coverage_mask()); rc = self.run_prep(d, base)
            names = {p.stem for p in (base / "daily").glob("*.tif")}; self.assertNotIn(f"{low:%Y%m%d}", names); self.assertIn(f"{CTX[0]:%Y%m%d}", names); self.assertEqual(rc, 1)
            self.assertIn("LOW_COVERAGE_NOT_CONVERTED", (Path(d) / "out" / "tables" / "chirps_v3_sat_conversion.csv").read_text())
        with tempfile.TemporaryDirectory() as d:                                                                                         # explicit opt-in: converted, labelled, rc still non-zero
            low = CTX[1]; base = self.build(d, CTX[:3], low=(low,), low_masked=low_coverage_mask()); rc = self.run_prep(d, base, "--include-low-coverage")
            with rasterio.open(base / "daily" / f"{low:%Y%m%d}.tif") as ds: self.assertIn("LOW_COVERAGE", ds.tags()["coverage_status"])
            self.assertIn("CONVERTED_LOW_COVERAGE", (Path(d) / "out" / "tables" / "chirps_v3_sat_conversion.csv").read_text()); self.assertEqual(rc, 1)
            self.assertEqual(json.loads((base / "source.json").read_text())["low_coverage_dates_included"], 1)

    def test_no_assert_statements_in_production_processing(self):
        import re
        for f in ("prepare_chirps_rainfall.py", "fetch_chirps_rainfall.py"):
            self.assertIsNone(re.search(r"^\s*assert\s", (ROOT / "scripts" / f).read_text(encoding="utf-8"), re.M), f)

    def test_failed_readback_raises_and_leaves_no_partial_output(self):
        with tempfile.TemporaryDirectory() as d:
            base = self.build(d, CTX[:1]); raw = base / "raw" / CA.raw_name(CTX[0]); out = Path(d) / "o.tif"
            with mock.patch.object(self.prep.np, "array_equal", return_value=False):
                with self.assertRaises(self.prep.ConversionError) as cm: self.prep.convert_one(raw, out, CTX[0], {"sha256": "x"})
            self.assertIn("read-back values differ", str(cm.exception)); self.assertFalse(out.exists()); self.assertFalse(Path(str(out) + ".part").exists())
            res = self.prep.convert_one(raw, out, CTX[0], {"sha256": "x"}); self.assertTrue(out.exists()); self.assertFalse(Path(str(out) + ".part").exists()); self.assertGreater(res["valid_cells"], 0)
            bad = Path(d) / "bad.tif"; bad.write_bytes(b"junk")
            with self.assertRaises(self.prep.ConversionError): self.prep.convert_one(bad, Path(d) / "b.tif", CTX[0], {"sha256": "x"})
            self.assertFalse((Path(d) / "b.tif").exists())

    def test_conversion_failure_is_reported_and_stale_outputs_are_removed(self):
        with tempfile.TemporaryDirectory() as d:
            base = self.build(d, CTX[:2]); daily = base / "daily"; daily.mkdir()
            (daily / f"{CTX[0]:%Y%m%d}.tif").write_bytes(b"stale output from an earlier run"); (daily / "20150722.tif.part").write_bytes(b"half written")
            (daily / f"{CTX[5]:%Y%m%d}.tif").write_bytes(b"stale output for a date that is no longer acquired")                                 # CTX[5] has no manifest entry
            with mock.patch.object(self.prep.np, "array_equal", return_value=False): rc = self.run_prep(d, base)
            self.assertEqual(rc, 1); self.assertEqual(list(daily.glob("*.tif")), []); self.assertEqual(list(daily.glob("*.part")), [])          # nothing half-written or stale survives
            txt = (Path(d) / "out" / "tables" / "chirps_v3_sat_conversion.csv").read_text(); self.assertIn("CONVERSION_FAILED", txt); self.assertIn("stale daily file", txt)   # the MISSING date's stale file is removed AND noted


class TestComparison(unittest.TestCase):
    def test_lag_detects_shift_and_strict_nan(self):
        dates = [date(2015, 11, 1) + timedelta(days=i) for i in range(30)]
        base = np.zeros(30); base[10], base[11], base[20] = 50.0, 100.0, 30.0
        ch = np.roll(base, 1)                                                                    # CHIRPS label is one day LATER than IMD for the same rain
        rows = RC.lag_stats(base, ch, dates); best = max((r for r in rows if r["pearson_r"] is not None), key=lambda r: r["pearson_r"])
        self.assertEqual(best["lag_days"], 1); self.assertAlmostEqual(best["pearson_r"], 1.0, places=6)
        imd = base.copy(); imd[11] = np.nan; self.assertEqual([r for r in RC.lag_stats(imd, ch, dates) if r["lag_days"] == 0][0]["n_pairs"], 29)
        self.assertIsNone(RC.lag_stats(base[:5], ch[:5], dates[:5])[0]["pearson_r"])             # <8 pairs -> no correlation claimed

    def test_two_day_split_diagnostic(self):
        dates = [date(2015, 11, 30) + timedelta(days=i) for i in range(4)]
        imd = np.array([0, 5.0, 150.0, 1.0]); ch = np.array([0, 140.0, 15.0, 1.0])
        r = RC.two_day_split(imd, ch, dates, date(2015, 12, 1), date(2015, 12, 2))
        self.assertEqual((r["imd_d1"], r["chirps_d1"]), (5.0, 140.0)); self.assertAlmostEqual(r["two_day_sum_ratio_chirps_to_imd"], 155.0 / 155.0)
        r2 = RC.two_day_split(imd, ch, dates, date(2015, 12, 5), date(2015, 12, 6)); self.assertIsNone(r2["imd_d1"]); self.assertIsNone(r2["two_day_sum_ratio_chirps_to_imd"])

    def test_chirps_area_mean_support_and_strictness(self):
        tr = Affine(0.05, 0, 80.0, 0, -0.05, 13.3); cube = np.ones((2, 6, 6)); cube[0, 0, 0] = 5.0; cube[1, 2, 2] = np.nan
        region = box(80.0, 13.0, 80.3, 13.3)                                                      # exactly the 6x6 window
        ser, sup, n = RC.chirps_area_mean(cube, tr, region); self.assertAlmostEqual(sup, 1.0); self.assertEqual(n, 36)
        self.assertAlmostEqual(ser[0], (35 + 5) / 36); self.assertTrue(np.isnan(ser[1]))             # one NaN cell -> NaN, never averaged over the remainder
        big = box(80.0, 12.8, 80.3, 13.3); _, sup2, _ = RC.chirps_area_mean(cube, tr, big); self.assertAlmostEqual(sup2, 0.6)         # window covers 60 % of the footprint
        far = box(81.0, 12.0, 81.2, 12.2); s3, sup3, n3 = RC.chirps_area_mean(cube, tr, far); self.assertEqual((sup3, n3), (0.0, 0)); self.assertTrue(np.isnan(s3).all())

    def test_imd_coverage_lists_cells_and_never_fills(self):
        itr = Affine(0.25, 0, 66.375, 0, -0.25, 38.625); cube = np.full((3, 129, 135), np.nan); cells = RC.imd_cells_over_aoi(itr, (129, 135), AOI)
        self.assertEqual(len(cells), 3); self.assertAlmostEqual(sum(c["aoi_share"] for c in cells), 1.0, places=6)
        mid = [c for c in cells if abs(c["centre"][1] - 13.0) < 1e-6][0]; cube[:, mid["row"], mid["col"]] = 7.0; cube[1, mid["row"], mid["col"]] = np.nan
        cov = RC.imd_aoi_coverage_by_day(cube, cells); self.assertAlmostEqual(cov[0], mid["aoi_share"]); self.assertEqual(cov[1], 0.0); self.assertLess(cov[0], 1.0)

    def test_end_to_end_script_on_synthetic_dirs(self):
        cmp_ = load("compare_chirps_imd"); import geopandas as gpd
        with tempfile.TemporaryDirectory() as d:
            imd_dir, ch_dir = Path(d) / "imd", Path(d) / "chi"; imd_dir.mkdir(); ch_dir.mkdir()
            itr = Affine(0.25, 0, 66.375, 0, -0.25, 38.625); mid_r, mid_c = int((38.625 - 13.0) // 0.25), int((80.25 - 66.375) // 0.25)
            for i, dd in enumerate(CTX):
                a = np.full((129, 135), -9999.0, "float32"); a[mid_r, mid_c] = 100.0 if dd == date(2015, 12, 2) else 1.0
                with rasterio.open(imd_dir / f"{dd:%Y%m%d}.tif", "w", driver="GTiff", height=129, width=135, count=1, dtype="float32", crs="EPSG:4326", transform=itr, nodata=-9999.0) as ds: ds.write(a, 1)
                b = np.ones(SHAPE, "float32") * (100.0 if dd == date(2015, 12, 1) else 1.0)                          # CHIRPS peak one day EARLIER
                with rasterio.open(ch_dir / f"{dd:%Y%m%d}.tif", "w", driver="GTiff", height=SHAPE[0], width=SHAPE[1], count=1, dtype="float32", crs="EPSG:4326", transform=WTR, nodata=-9999.0) as ds: ds.write(b, 1)
            sa = gpd.GeoDataFrame(geometry=[AOI], crs=4326); old, oa = status.STATUS_FILE, sys.argv; status.STATUS_FILE = Path(d) / "s.json"
            sys.argv = ["x", "--imd-dir", str(imd_dir), "--chirps-dir", str(ch_dir), "--outputs-dir", str(Path(d) / "o"), "--min-support", "1.01"]            # support can never reach 101 % -> footprint mode must be refused
            try:
                with mock.patch.object(cmp_, "load_study_area", return_value=(sa, sa, {})): cmp_.main()
            finally: status.STATUS_FILE, sys.argv = old, oa
            rep = (Path(d) / "o" / "reports" / "chirps_vs_imd_comparison.md").read_text()
            self.assertIn("Not a validation", rep); self.assertIn("with any valid data in the window: 1", rep); self.assertIn("NOT filled from CHIRPS", rep)
            self.assertIn("covers only", rep)                                                    # footprint comparison refused: window covers < 50 % of the 0.25 deg cell
            import csv
            lags = list(csv.DictReader(open(Path(d) / "o" / "tables" / "chirps_vs_imd_lags.csv")))
            foc = [r for r in lags if r["scope"] == "focus_window" and r["mode"] == "aoi_part" and r["pearson_r"]]
            best = max(foc, key=lambda r: float(r["pearson_r"])); self.assertEqual(int(best["lag_days"]), -1)          # CHIRPS[d-1] matches IMD[d]
            self.assertTrue((Path(d) / "o" / "figures" / "chirps_vs_imd_timeseries.png").exists())


if __name__ == "__main__":
    unittest.main()


class TestPostAcquisitionAudit(unittest.TestCase):
    """28 vs 29 AOI-cell discrepancy, stale 'partial' status, antecedent-window date logic (all SYNTHETIC)."""
    PX = 0.05

    def grid(self): return Affine(self.PX, 0, 80.0, 0, -self.PX, 13.0), (6, 8)

    def test_one_convention_and_sliver_cell_is_counted_by_both_code_paths(self):
        T, sh = self.grid()
        aoi = box(80.06, 12.76, 80.24, 12.96).union(box(80.24, 12.9549999, 80.3000001, 12.96))     # a thin strip reaching a neighbouring cell by 1e-7 deg
        w_wf = R.cell_weights(T, sh, aoi); w_acq, touch = chirps.aoi_cell_weights(T, sh, aoi)
        np.testing.assert_array_equal(w_wf, w_acq)                                                    # identical: one implementation
        self.assertEqual(int((w_wf > 0).sum()), int(touch.sum()))                                     # same cell count in acquisition and workflow
        self.assertAlmostEqual(float(w_wf.sum()), 1.0, places=9)                                      # exact polygon-area weights sum to 1
        tiny = w_wf[(w_wf > 0) & (w_wf < 1e-4)]; self.assertGreaterEqual(tiny.size, 1)                # at least one sliver cell with a true tiny weight
        # the former 10x rasterisation misses such slivers (documents the root cause of 28 vs 29)
        from rasterio import features
        fine = features.rasterize([(aoi, 1)], out_shape=(sh[0] * 10, sh[1] * 10), transform=Affine(self.PX / 10, 0, 80.0, 0, -self.PX / 10, 13.0), fill=0, dtype="uint8")
        old_cnt = int((fine.reshape(sh[0], 10, sh[1], 10).sum(axis=(1, 3)) > 0).sum())
        self.assertLess(old_cnt, int((w_wf > 0).sum()))

    def test_partial_boundary_cell_weight_is_exact_area_share(self):
        T, sh = self.grid()
        aoi = box(80.05, 12.80, 80.125, 12.90)                                                         # covers cell col1 fully, col2 half; 2 rows
        w = R.cell_weights(T, sh, aoi)
        self.assertAlmostEqual(float(w.sum()), 1.0, places=12)
        cols = w.sum(axis=0); self.assertAlmostEqual(float(cols[1]), 2 / 3, places=9); self.assertAlmostEqual(float(cols[2]), 1 / 3, places=9)

    def test_edge_touching_cells_are_not_aoi_cells(self):
        T, sh = self.grid()
        w = R.cell_weights(T, sh, box(80.05, 12.80, 80.15, 12.90))                                     # exactly aligned: neighbours share only an edge
        self.assertEqual(int((w > 0).sum()), 4)

    def test_weighted_stats_use_exact_weights_including_sliver(self):
        T, sh = self.grid(); aoi = box(80.06, 12.76, 80.24, 12.96).union(box(80.24, 12.9549999, 80.3000001, 12.96))
        w = R.cell_weights(T, sh, aoi); mm = np.full(sh, 10.0); sl = (w > 0) & (w < 1e-4); mm[sl] = 1000.0
        st = R.weighted_stats(mm, w); self.assertEqual(st["cells_in_aoi"], int((w > 0).sum()))
        self.assertAlmostEqual(st["mean_mm"], float((mm * w).sum()), places=9)                          # area-weighted, sliver barely moves the mean
        self.assertLess(st["mean_mm"], 10.5); self.assertEqual(st["max_mm"], 1000.0)
        mm[sl] = np.nan; self.assertAlmostEqual(R.weighted_stats(mm, w)["coverage"], float(w[~sl].sum()), places=12)    # missing sliver lowers coverage, not zero-filled

    def test_status_not_partial_for_complete_acquisition_source(self):
        src = (ROOT / "scripts" / "fetch_chirps_rainfall.py").read_text(encoding="utf-8")
        self.assertIn('status.record(SID, state,', src); self.assertNotIn('status.record(SID, status.PARTIAL', src); self.assertNotIn('status.record("CH3A", status.PARTIAL', src)     # SID defaults to "CH3A" (2015); see test_chirps_2021_isolation
        old = (ROOT / "scripts" / "fetch_chirps_rainfall.py").read_text(encoding="utf-8")
        self.assertIn("day definition provisional", old)                                               # caveat remains in the message

    def test_antecedent_windows_exact_dates_and_missing_days(self):
        T, sh = self.grid(); D = date(2015, 11, 15)
        dm = {D - timedelta(days=k): np.full((2, 2), float(k)) for k in range(0, 40)}                  # value = days before D
        for n in (1, 3, 7, 14, 30):
            t, miss = R.window_total(dm, D, n)
            self.assertEqual(miss, [])
            self.assertEqual(float(t[0, 0]), float(sum(range(1, n + 1))), n)                           # D-1..D-n included; D itself excluded
        t, _ = R.window_total(dm, D, 3, include_end_day=True); self.assertEqual(float(t[0, 0]), 0 + 1 + 2)
        dm[D - timedelta(days=5)] = None                                                                 # missing day inside 7- and 14-day windows only
        for n, expect_none in ((1, False), (3, False), (7, True), (14, True), (30, True)):
            t, miss = R.window_total(dm, D, n); self.assertEqual(t is None, expect_none, n)
            if expect_none: self.assertEqual(miss, [D - timedelta(days=5)])
        z = {D - timedelta(days=1): np.zeros((2, 2))}; t, miss = R.window_total(z, D, 3); self.assertIsNone(t)   # absent days are missing, not zero
        t, miss = R.window_total(z, D, 1); self.assertEqual(float(t[0, 0]), 0.0)                        # a genuine 0 mm day is a value
