"""Isolated CHIRPS 2021 run support: path isolation, status ids, defaults unchanged, preservation hashing. SYNTHETIC; no Earth Engine, no network."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import geopandas as gpd
import numpy as np
from shapely.geometry import box
from src.geospatial import chirps, chirps_acquire as CA, chirps_runpaths as RP, rainfall as R
from src.utils import paths, status


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


class TestResolve(unittest.TestCase):
    def test_defaults_unchanged_for_2015(self):
        for kind, sid in (("probe", "CH3"), ("acquire", "CH3A"), ("prepare", "CH3P")):
            r = RP.resolve_run_paths(kind, "2015_nov_dec")
            self.assertEqual(r["base"], (paths.DATA_EXT / "rainfall" / "chirps_v3_daily").resolve()); self.assertEqual(r["status_id"], sid)
            self.assertEqual((r["tables"], r["reports"], r["figures"]), ((paths.ROOT / "outputs" / "tables").resolve(), (paths.ROOT / "outputs" / "reports").resolve(), (paths.ROOT / "outputs" / "figures").resolve()))
        self.assertEqual(paths.DATA_EXT / "rainfall" / CA.SOURCE_ID, RP.default_base())

    def test_module_level_defaults_in_scripts_unchanged(self):
        self.assertEqual(load("probe_chirps_coverage").BASE, paths.DATA_EXT / "rainfall" / "chirps_v3_daily"); self.assertEqual(load("fetch_chirps_rainfall").RAW, paths.DATA_EXT / "rainfall" / "chirps_v3_daily" / "raw")

    def test_custom_paths_honoured(self):
        with tempfile.TemporaryDirectory() as d:
            r = RP.resolve_run_paths("probe", "2021_sep_nov", Path(d) / "c21", Path(d) / "o21", "CH3_2021")
            self.assertEqual(r["base"], (Path(d) / "c21").resolve()); self.assertEqual(r["tables"], (Path(d) / "o21" / "tables").resolve()); self.assertEqual(r["status_id"], "CH3_2021")
            r15 = RP.resolve_run_paths("acquire", "2015_nov_dec", Path(d) / "x", Path(d) / "y"); self.assertEqual(r15["status_id"], "CH3A")      # custom dirs allowed for 2015 too

    def test_2021_cannot_target_2015_locations(self):
        with tempfile.TemporaryDirectory() as d:
            ok = dict(base_dir=Path(d) / "c", outputs_dir=Path(d) / "o", status_id="CH3A_2021")
            RP.resolve_run_paths("acquire", "2021_sep_nov", **ok)
            for bad in ({"base_dir": None}, {"base_dir": RP.default_base()}, {"base_dir": RP.default_base() / "sub"}, {"base_dir": RP.default_base().parent},
                        {"outputs_dir": None}, {"outputs_dir": RP.default_outputs()}, {"outputs_dir": RP.default_outputs() / "reports"}, {"outputs_dir": paths.ROOT},
                        {"status_id": None}, {"status_id": "CH3A"}):
                with self.assertRaises(RP.PathIsolationError, msg=str(bad)): RP.resolve_run_paths("acquire", "2021_sep_nov", **{**ok, **bad})

    def test_distinct_status_ids_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            old = status.STATUS_FILE; status.STATUS_FILE = Path(d) / "status.json"
            try:
                status.record("CH3", status.PARTIAL, "2015 probe"); status.record("CH3_2021", status.BLOCKED, "2021 probe")
                m = json.loads(status.STATUS_FILE.read_text())["modules"]; self.assertEqual((m["CH3"]["message"], m["CH3_2021"]["message"]), ("2015 probe", "2021 probe"))
                for k in ("CH3_2021", "CH3A_2021", "CH3P_2021"): self.assertIn(k, dict(status.MODULES))
            finally: status.STATUS_FILE = old

    def test_cache_reuse_requires_matching_window_and_cells(self):
        cj = {"window": ["2021-08-06", "2021-11-28"], "cells_touching_aoi": 12, "crs": "EPSG:4326", "per_date": {str(i): {} for i in range(115)}}
        self.assertTrue(RP.probe_cache_reusable(cj, "2021-08-06", "2021-11-28", 12, "EPSG:4326", 115))
        for args in (("2021-08-07", "2021-11-28", 12, "EPSG:4326", 115), ("2021-08-06", "2021-11-27", 12, "EPSG:4326", 115), ("2021-08-06", "2021-11-28", 13, "EPSG:4326", 115),
                     ("2021-08-06", "2021-11-28", 12, "EPSG:32644", 115), ("2021-08-06", "2021-11-28", 12, "EPSG:4326", 114)):
            self.assertFalse(RP.probe_cache_reusable(cj, *args), args)
        self.assertFalse(RP.probe_cache_reusable(None, "a", "b", 1, "c", 1)); self.assertFalse(RP.probe_cache_reusable({"window": 5}, "a", "b", 1, "c", 1))

    def test_event_config(self):
        ev = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"]
        e = ev["2021_sep_nov"]; self.assertEqual(e["context_window"], ["2021-08-06", "2021-11-28"]); self.assertEqual(len(R.daterange(*e["context_window"])), 115)
        self.assertEqual(ev["2015_nov_dec"]["context_window"], ["2015-07-21", "2015-12-20"]); self.assertEqual(ev["2015_nov_dec"]["event_window_proposed"], ["2015-11-08", "2015-12-05"])
        s1 = json.loads((paths.CONFIG / "s1_preprocess.json").read_text())["dates"]; self.assertEqual((date.fromisoformat(s1[0]) - date.fromisoformat(e["context_window"][0])).days, 30); self.assertEqual(s1[-1], e["context_window"][1])
        self.assertTrue(set(e["probe_test_dates"]) <= {x.isoformat() for x in R.daterange(*e["context_window"])})


class TestPreservationTool(unittest.TestCase):
    def test_snapshot_detects_modify_delete_and_ignores_new(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "data/external/rainfall/chirps_v3_daily/raw").mkdir(parents=True); (root / "outputs/reports").mkdir(parents=True)
            (root / "data/external/rainfall/chirps_v3_daily/raw/a.tif").write_bytes(b"1"); (root / "outputs/reports/chirps_v3_sat_probe.json").write_text("{}")
            (root / "data/external/rainfall/chirps_v3_daily_2021").mkdir(parents=True); (root / "data/external/rainfall/chirps_v3_daily_2021/x.tif").write_bytes(b"z")     # NOT protected
            s0 = RP.snapshot(root); self.assertEqual(len(s0), 2)
            self.assertEqual(RP.compare(s0, RP.snapshot(root)), {"unchanged": 2, "modified": [], "deleted": [], "added": []})
            (root / "data/external/rainfall/chirps_v3_daily/raw/new.tif").write_bytes(b"n"); (root / "data/external/rainfall/chirps_v3_daily/raw/a.tif").write_bytes(b"2"); (root / "outputs/reports/chirps_v3_sat_probe.json").unlink()
            r = RP.compare(s0, RP.snapshot(root)); self.assertEqual((len(r["modified"]), len(r["deleted"]), len(r["added"])), (1, 1, 1))


def stub_ee_failing():
    m = types.ModuleType("ee")
    def boom(*a, **k): raise RuntimeError("simulated: Earth Engine unavailable")
    m.ImageCollection = boom; return m


class TestScriptsIsolation(unittest.TestCase):
    """The scripts are driven with Earth Engine STUBBED to fail at the first call: proves path/status handling and that nothing reaches the 2015 locations. No EE, no network."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.old = status.STATUS_FILE; status.STATUS_FILE = self.tmp / "status.json"
        status.STATUS_FILE.write_text(json.dumps({"modules": {"CH3": {"state": "PARTIALLY COMPLETED", "message": "2015 probe"}, "CH3A": {"state": "COMPLETED", "message": "2015 acquisition"}, "CH3P": {"state": "COMPLETED", "message": "2015 prep"}}}))
        self.s0 = status.STATUS_FILE.read_text(); sa = gpd.GeoDataFrame(geometry=[box(80.18, 13.0, 80.24, 13.06)], crs=4326)
        self.stub = stub_ee_failing(); self.sa = sa
        from src.flood_detection import gee_sentinel1 as g1
        self.ps = [mock.patch.dict(sys.modules, {"ee": self.stub}), mock.patch.object(g1, "init_ee", lambda *a, **k: None)]
        for p in self.ps: p.start()
        self.guard = tree(RP.default_base()) if RP.default_base().exists() else {}

    def tearDown(self):
        for p in self.ps: p.stop()
        status.STATUS_FILE = self.old

    def run_script(self, name, *args):
        m = load(name); buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["x", *args]), mock.patch.object(m, "load_study_area", lambda: (self.sa, self.sa, {})), contextlib.redirect_stdout(buf): rc = m.main()
        return rc, buf.getvalue()

    def reg(self): return json.loads(status.STATUS_FILE.read_text())["modules"]

    def test_probe_and_fetch_2021_refuse_default_paths(self):
        for name, extra in (("probe_chirps_coverage", ()), ("fetch_chirps_rainfall", ())):
            rc, out = self.run_script(name, "--event", "2021_sep_nov", *extra); self.assertEqual(rc, 2); self.assertIn("path isolation", out)
            rc, out = self.run_script(name, "--event", "2021_sep_nov", "--base-dir", str(self.tmp / "c"), "--outputs-dir", str(self.tmp / "o")); self.assertEqual(rc, 2); self.assertIn("status id", out)
        self.assertEqual(status.STATUS_FILE.read_text(), self.s0); self.assertFalse((self.tmp / "c").exists())                   # refused BEFORE anything was created or recorded

    def test_probe_2021_writes_only_under_isolated_dirs_with_own_status_id(self):
        rc, out = self.run_script("probe_chirps_coverage", "--event", "2021_sep_nov", "--base-dir", str(self.tmp / "c21"), "--outputs-dir", str(self.tmp / "o21"), "--status-id", "CH3_2021")
        self.assertEqual(rc, 2); self.assertIn("Earth Engine", out)                                                                # stub EE failed at the metadata step
        m = self.reg(); self.assertEqual(m["CH3"]["message"], "2015 probe"); self.assertEqual(m["CH3_2021"]["state"], status.BLOCKED)
        self.assertTrue((self.tmp / "c21" / "probe").is_dir()); self.assertEqual(self.guard, tree(RP.default_base()) if RP.default_base().exists() else {})

    def test_fetch_2021_uses_isolated_dirs_and_probe_json_from_outputs_dir(self):
        o = self.tmp / "o21"; (o / "reports").mkdir(parents=True); (o / "reports" / "chirps_v3_sat_probe.json").write_text("{}")
        rc, out = self.run_script("fetch_chirps_rainfall", "--event", "2021_sep_nov", "--base-dir", str(self.tmp / "c21"), "--outputs-dir", str(o), "--status-id", "CH3A_2021")
        self.assertEqual(rc, 2); m = self.reg(); self.assertEqual(m["CH3A"]["message"], "2015 acquisition"); self.assertEqual(m["CH3A_2021"]["state"], status.BLOCKED)
        self.assertTrue((self.tmp / "c21" / "raw").is_dir())

    def test_default_2015_probe_still_targets_default_status_id(self):
        # no path args: resolves to the 2015 defaults (CH3); we only verify the id/paths via the resolver, not by writing into the real directories
        self.assertEqual(RP.resolve_run_paths("probe", "2015_nov_dec")["status_id"], "CH3")


class TestPrepare2021(unittest.TestCase):
    def test_prepare_isolated_2021_directory(self):
        spec = importlib.util.spec_from_file_location("tca", ROOT / "tests" / "test_chirps_acquire.py"); T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
        prep = load("prepare_chirps_rainfall"); ctx = R.daterange("2021-08-06", "2021-11-28")
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "chirps_v3_daily_2021"; raw = base / "raw"; raw.mkdir(parents=True); man = {"dataset": chirps.DATASET_ID, "crs": "EPSG:4326", "retrieval_started_utc": "2026-11-24T00:00:00+00:00", "entries": {}}
            for dd in ctx:
                f = raw / CA.raw_name(dd); T.write_raw(f, dd); man["entries"][dd.isoformat()] = {"date": dd.isoformat(), "status": "OK", "sha256": CA.sha256_file(f), "file": f.name}
            CA.save_manifest(raw / "download_manifest.json", man); old = status.STATUS_FILE; status.STATUS_FILE = Path(d) / "status.json"
            try:
                with mock.patch.object(sys, "argv", ["x", "--event", "2021_sep_nov", "--base-dir", str(base), "--outputs-dir", str(Path(d) / "out21"), "--status-id", "CH3P_2021"]), contextlib.redirect_stdout(io.StringIO()): rc = prep.main()
                self.assertEqual(rc, 0); self.assertEqual(len(list((base / "daily").glob("*.tif"))), 115); src = json.loads((base / "source.json").read_text()); self.assertEqual(src["source_id"], "chirps_v3_daily_2021")
                self.assertEqual(json.loads(status.STATUS_FILE.read_text())["modules"]["CH3P_2021"]["state"], status.COMPLETED); self.assertNotIn("CH3P", json.loads(status.STATUS_FILE.read_text())["modules"])
                with mock.patch.object(sys, "argv", ["x", "--event", "2021_sep_nov", "--base-dir", str(base), "--outputs-dir", str(Path(d) / "out21")]), contextlib.redirect_stdout(io.StringIO()) as b: rc = prep.main()
                self.assertEqual(rc, 2); self.assertIn("path isolation", b.getvalue())                                              # missing --status-id: refused
            finally: status.STATUS_FILE = old


# ============================================================== corrective patch: outputs/chirps_2021, all 2015 status ids, cache fingerprints
from shapely.geometry import Polygon
from rasterio.transform import Affine

SCRIPTS = (("probe", "probe_chirps_coverage"), ("acquire", "fetch_chirps_rainfall"), ("prepare", "prepare_chirps_rainfall"))


class TestOutputIsolationCorrection(unittest.TestCase):
    def test_intended_2021_output_dir_is_accepted(self):
        o = RP.default_outputs()
        for kind, _ in SCRIPTS:
            r = RP.resolve_run_paths(kind, "2021_sep_nov", RP.default_base().parent / "chirps_v3_daily_2021", o / "chirps_2021", f"{RP.DEFAULT_STATUS[kind]}_2021")
            self.assertEqual(r["reports"], (o / "chirps_2021" / "reports").resolve()); self.assertEqual(r["tables"], (o / "chirps_2021" / "tables").resolve()); self.assertEqual(r["figures"], (o / "chirps_2021" / "figures").resolve())
            for k in ("reports", "tables", "figures"): self.assertNotEqual(r[k], (o / k).resolve())                       # never the 2015 folders
        RP.resolve_run_paths("probe", "2021_sep_nov", RP.default_base().parent / "chirps_v3_daily_2021", o / "chirps_2021", "CH3_2021")
        RP.resolve_run_paths("probe", "2021_sep_nov", RP.default_base().parent / "chirps_v3_daily_2021", o / "other_run", "CH3_2021")     # any non-protected sibling is fine

    def test_2015_output_locations_remain_rejected(self):
        o = RP.default_outputs(); base = RP.default_base().parent / "chirps_v3_daily_2021"
        for bad in (o, o / "reports", o / "tables", o / "figures", o / "reports" / "x", o / "tables" / "x" / "y", o / "figures" / "chirps_2021", paths.ROOT, o.parent):
            for kind, _ in SCRIPTS:
                with self.assertRaises(RP.PathIsolationError, msg=f"{kind} {bad}"): RP.resolve_run_paths(kind, "2021_sep_nov", base, bad, f"{RP.DEFAULT_STATUS[kind]}_2021")

    def test_default_2015_run_and_custom_2015_dirs_unchanged(self):
        for kind, sid in (("probe", "CH3"), ("acquire", "CH3A"), ("prepare", "CH3P")):
            r = RP.resolve_run_paths(kind, "2015_nov_dec"); self.assertEqual((r["outputs"], r["status_id"]), (RP.default_outputs(), sid))
            RP.resolve_run_paths(kind, "2015_nov_dec", outputs_dir=RP.default_outputs() / "reports")                       # the 2015 event itself is not restricted

    def test_2021_run_directories_do_not_touch_2015_files(self):
        with tempfile.TemporaryDirectory() as d:                                                                              # same relative layout as the real repo, in a sandbox root
            root = Path(d); (root / "outputs" / "reports").mkdir(parents=True); f = root / "outputs" / "reports" / "chirps_v3_sat_probe.json"; f.write_text("2015")
            run = root / "outputs" / "chirps_2021"; (run / "reports").mkdir(parents=True); (run / "reports" / "chirps_v3_sat_probe.json").write_text("2021")
            self.assertEqual(f.read_text(), "2015")
            self.assertNotIn("outputs/chirps_2021/reports/chirps_v3_sat_probe.json", RP.protected_2015_files(root))          # 2021 evidence is not mistaken for 2015 evidence
            self.assertIn("outputs/reports/chirps_v3_sat_probe.json", RP.protected_2015_files(root))


class TestStatusIdCorrection(unittest.TestCase):
    def test_all_three_2015_ids_rejected_for_every_kind(self):
        with tempfile.TemporaryDirectory() as d:
            for kind, _ in SCRIPTS:
                for sid in ("CH3", "CH3A", "CH3P", None):
                    with self.assertRaises(RP.PathIsolationError, msg=f"{kind} {sid}"): RP.resolve_run_paths(kind, "2021_sep_nov", Path(d) / "c", Path(d) / "o", sid)
                RP.resolve_run_paths(kind, "2021_sep_nov", Path(d) / "c", Path(d) / "o", "CH3_2021")                           # a distinct id is accepted for any kind
        self.assertEqual(RP.PROTECTED_STATUS_IDS, {"CH3", "CH3A", "CH3P"})

    def test_cross_script_status_id_rejection_before_any_write(self):
        sa = gpd.GeoDataFrame(geometry=[box(80.18, 13.0, 80.24, 13.06)], crs=4326)
        for _, name in SCRIPTS:
            for sid in ("CH3", "CH3A", "CH3P"):
                with tempfile.TemporaryDirectory() as d:
                    old = status.STATUS_FILE; status.STATUS_FILE = Path(d) / "status.json"; status.STATUS_FILE.write_text('{"modules": {"CH3": {"message": "2015"}}}'); s0 = status.STATUS_FILE.read_text()
                    m = load(name); buf = io.StringIO()
                    try:
                        with mock.patch.object(sys, "argv", ["x", "--event", "2021_sep_nov", "--base-dir", str(Path(d) / "c"), "--outputs-dir", str(Path(d) / "o"), "--status-id", sid]), \
                             mock.patch.object(m, "load_study_area", lambda: (sa, sa, {}), create=True), contextlib.redirect_stdout(buf): rc = m.main()
                        self.assertEqual(rc, 2, f"{name} {sid}"); self.assertIn("2015 registry entry", buf.getvalue())
                        self.assertEqual(status.STATUS_FILE.read_text(), s0); self.assertFalse((Path(d) / "c").exists()); self.assertFalse((Path(d) / "o").exists())
                    finally: status.STATUS_FILE = old


TRF = Affine(0.05, 0, 80.0, 0, -0.05, 13.5)
SH = (6, 6)


class TestProbeCacheFingerprints(unittest.TestCase):
    def setUp(self):
        self.aoi = Polygon([(80.07, 13.30), (80.21, 13.32), (80.17, 13.12), (80.06, 13.16)])
        self.w, self.touch = chirps.aoi_cell_weights(TRF, SH, self.aoi)
        self.win = ("2021-08-06", "2021-11-28"); self.n = int(self.touch.sum()); self.crs = "EPSG:4326"
        self.cj = {"window": list(self.win), "cells_touching_aoi": self.n, "crs": self.crs, "per_date": {str(i): {} for i in range(115)},
                   "aoi_fingerprint": RP.aoi_fingerprint(self.aoi), "weights_fingerprint": RP.weights_fingerprint(self.w)}

    def ok(self, cj=None, aoi=None, w=None, n=None):
        return RP.probe_cache_matches(self.cj if cj is None else cj, *self.win, self.n if n is None else n, self.crs, 115, RP.aoi_fingerprint(aoi or self.aoi), RP.weights_fingerprint(self.w if w is None else w))

    def test_matching_cache_is_reused(self):
        self.assertTrue(self.ok()); self.assertTrue(self.ok(aoi=Polygon(list(self.aoi.exterior.coords)[::-1])))      # vertex order does not matter

    def test_changed_geometry_same_cell_count_is_not_reused(self):
        moved = Polygon([(x + 0.002, y - 0.002) for x, y in self.aoi.exterior.coords])                                       # small shift, still the same touched cells
        w2, t2 = chirps.aoi_cell_weights(TRF, SH, moved); self.assertEqual(int(t2.sum()), self.n)                          # premise: identical cell count
        self.assertTrue(RP.probe_cache_reusable(self.cj, *self.win, self.n, self.crs, 115))                                  # the old count-only rule would have accepted it
        self.assertFalse(self.ok(aoi=moved, w=w2)); self.assertNotEqual(RP.aoi_fingerprint(moved), RP.aoi_fingerprint(self.aoi))

    def test_changed_weights_same_geometry_and_cells_is_not_reused(self):
        w2 = self.w.copy(); idx = np.argwhere(self.touch)[:2]; w2[tuple(idx[0])] += 1e-6; w2[tuple(idx[1])] -= 1e-6              # same cells, same total, different weights
        self.assertEqual(int((w2 > 0).sum()), int((self.w > 0).sum())); self.assertFalse(self.ok(w=w2)); self.assertNotEqual(RP.weights_fingerprint(w2), RP.weights_fingerprint(self.w))

    def test_both_fingerprints_required_and_old_caches_not_reused(self):
        for drop in ("aoi_fingerprint", "weights_fingerprint"):
            cj = {k: v for k, v in self.cj.items() if k != drop}; self.assertFalse(self.ok(cj=cj), drop)                       # missing = not reusable (caches from before this patch)
        cj = dict(self.cj, weights_fingerprint="0" * 16); self.assertFalse(self.ok(cj=cj))
        cj = dict(self.cj, aoi_fingerprint="0" * 16); self.assertFalse(self.ok(cj=cj))
        self.assertFalse(self.ok(n=self.n + 1)); self.assertFalse(RP.probe_cache_matches(self.cj, *self.win, self.n, self.crs, 115, None, None))                    # window/count rules still apply

    def test_fingerprints_stable_and_noise_tolerant(self):
        self.assertEqual(RP.aoi_fingerprint(self.aoi), RP.aoi_fingerprint(Polygon([(x + 1e-12, y) for x, y in self.aoi.exterior.coords])))
        self.assertEqual(RP.weights_fingerprint(self.w), RP.weights_fingerprint(self.w + 1e-13))

    def test_probe_script_writes_and_checks_fingerprints(self):
        src = (ROOT / "scripts" / "probe_chirps_coverage.py").read_text(encoding="utf-8")
        self.assertIn("RP.probe_cache_matches(cj,", src); self.assertIn('"aoi_fingerprint": AOI_FP, "weights_fingerprint": W_FP', src); self.assertNotIn("RP.probe_cache_reusable(cj,", src)


class TestPreservationOfDefaults(unittest.TestCase):
    def test_2015_event_config_and_registry_entries_untouched(self):
        cfg = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8"))["events"]["2015_nov_dec"]
        self.assertEqual((cfg["context_window"], cfg["event_window_proposed"], cfg["antecedent_windows_days"], cfg["max_k_day"]), (["2015-07-21", "2015-12-20"], ["2015-11-08", "2015-12-05"], [1, 3, 7, 14, 30], [1, 3, 5]))
        mods = dict(status.MODULES); self.assertEqual((mods["CH3"], mods["CH3A"], mods["CH3P"]), ("CHIRPS v3 DAILY_SAT: coverage probe (V2.3)", "CHIRPS v3 DAILY_SAT: controlled acquisition of the 153-day window (V2.3)", "CHIRPS v3 DAILY_SAT: prepare workflow-ready daily rasters (V2.3)"))


if __name__ == "__main__":
    unittest.main()
