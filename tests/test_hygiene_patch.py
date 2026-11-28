"""Hygiene patch: rainfall_workflow --status-id isolation, preservation --snapshot no-overwrite, exact probe-cache date keys. SYNTHETIC; no Earth Engine, no network."""
import contextlib
import importlib.util
import io
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.geospatial import chirps_runpaths as RP, rainfall as R
from src.utils import status


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def run(m, *args):
    buf = io.StringIO()
    with mock.patch.object(sys, "argv", ["x", *args]), contextlib.redirect_stdout(buf): rc = m.main()
    return rc, buf.getvalue()


class TestResolveStatusId(unittest.TestCase):
    def test_2015_defaults_unchanged(self):
        self.assertEqual(RP.resolve_status_id("2015_nov_dec", None, "C2", RP.PROTECTED_STATUS_IDS), "C2")
        self.assertEqual(RP.resolve_status_id("2015_nov_dec", "C2_custom", "C2", RP.PROTECTED_STATUS_IDS), "C2_custom")        # the 2015 event itself is not restricted

    def test_non_2015_event_rejects_every_reserved_id_and_none(self):
        for sid in (None, "C2", "CH3", "CH3A", "CH3P"):
            with self.assertRaises(RP.PathIsolationError, msg=str(sid)): RP.resolve_status_id("2021_sep_nov", sid, "C2", RP.PROTECTED_STATUS_IDS)
        self.assertEqual(RP.resolve_status_id("2021_sep_nov", "C2_2021", "C2", RP.PROTECTED_STATUS_IDS), "C2_2021")
        self.assertIn("C2_2021", dict(status.MODULES))


class TestRainfallWorkflowStatusId(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.old = status.STATUS_FILE; status.STATUS_FILE = self.tmp / "status.json"
        status.STATUS_FILE.write_text(json.dumps({"modules": {"C2": {"state": "COMPLETED", "message": "2015/IMD rainfall run"}}})); self.s0 = status.STATUS_FILE.read_text()
        self.m = load("rainfall_workflow")
        self.base = ["--source-id", "chirps_2021", "--input-dir", str(self.tmp / "in"), "--out-dir", str(self.tmp / "proc"), "--outputs-dir", str(self.tmp / "o")]

    def tearDown(self): status.STATUS_FILE = self.old

    def reg(self): return json.loads(status.STATUS_FILE.read_text())["modules"]

    def test_2021_without_or_with_reserved_status_id_is_refused_before_any_write(self):
        for extra in ((), ("--status-id", "C2"), ("--status-id", "CH3P")):
            rc, out = run(self.m, "--event", "2021_sep_nov", *self.base, *extra)
            self.assertEqual(rc, 2, extra); self.assertIn("status id isolation", out)
            self.assertEqual(status.STATUS_FILE.read_text(), self.s0); self.assertFalse((self.tmp / "o").exists()); self.assertFalse((self.tmp / "proc").exists())

    def test_2021_with_own_id_records_under_that_id_only(self):
        rc, _ = run(self.m, "--event", "2021_sep_nov", *self.base, "--status-id", "C2_2021")       # no source.json in the temp input dir -> BLOCKED, recorded under the chosen id
        self.assertNotEqual(rc, 2); m = self.reg(); self.assertEqual(m["C2"]["message"], "2015/IMD rainfall run"); self.assertEqual(m["C2_2021"]["state"], status.BLOCKED)

    def test_default_2015_run_still_records_under_c2(self):
        run(self.m, "--event", "2015_nov_dec", *self.base); m = self.reg()
        self.assertEqual(m["C2"]["state"], status.BLOCKED); self.assertNotIn("C2_2021", m)                  # default behaviour: the C2 entry, exactly as before
        self.assertEqual(self.m.STATUS_ID, "C2")

    def test_no_hardcoded_c2_left_in_status_calls(self):
        src = (ROOT / "scripts" / "rainfall_workflow.py").read_text(encoding="utf-8")
        self.assertNotIn('status.record("C2"', src); self.assertIn("status.record(STATUS_ID,", src); self.assertIn("--status-id", src)


class TestSnapshotNoOverwrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.root = self.tmp / "proj"; raw = self.root / "data/external/rainfall/chirps_v3_daily/raw"; raw.mkdir(parents=True)
        self.f = raw / "a.tif"; self.f.write_bytes(b"1"); self.snap = self.tmp / "baseline.json"; self.m = load("chirps_preservation_check")

    def test_existing_snapshot_is_refused_and_left_byte_identical(self):
        rc, _ = run(self.m, "--snapshot", str(self.snap), "--root", str(self.root)); self.assertEqual(rc, 0); b0 = self.snap.read_bytes()
        self.f.write_bytes(b"2")                                                                         # the protected file changes, then someone re-runs --snapshot
        rc, out = run(self.m, "--snapshot", str(self.snap), "--root", str(self.root)); self.assertEqual(rc, 2); self.assertIn("REFUSED", out); self.assertEqual(self.snap.read_bytes(), b0)
        rc, out = run(self.m, "--verify", str(self.snap), "--root", str(self.root)); self.assertEqual(rc, 1); self.assertIn("VIOLATION", out)          # the original baseline still exposes the change

    def test_explicit_overwrite_and_new_path_work(self):
        run(self.m, "--snapshot", str(self.snap), "--root", str(self.root)); b0 = self.snap.read_bytes(); self.f.write_bytes(b"2")
        rc, _ = run(self.m, "--snapshot", str(self.snap), "--root", str(self.root), "--overwrite"); self.assertEqual(rc, 0); self.assertNotEqual(self.snap.read_bytes(), b0)
        rc, _ = run(self.m, "--snapshot", str(self.tmp / "other.json"), "--root", str(self.root)); self.assertEqual(rc, 0)
        rc, out = run(self.m, "--verify", str(self.snap), "--root", str(self.root)); self.assertEqual(rc, 0); self.assertIn("PRESERVED", out)


class TestProbeCacheExactKeys(unittest.TestCase):
    def setUp(self):
        self.win = ("2021-08-06", "2021-11-28"); self.dates = [d.isoformat() for d in R.daterange(*self.win)]
        self.cj = {"window": list(self.win), "cells_touching_aoi": 29, "crs": "EPSG:4326", "per_date": {d: {} for d in self.dates}, "aoi_fingerprint": "a", "weights_fingerprint": "w"}

    def m(self, cj=None, expected=None): return RP.probe_cache_matches(self.cj if cj is None else cj, *self.win, 29, "EPSG:4326", 115, "a", "w", expected_dates=self.dates if expected is None else expected)

    def test_exact_keys_reused(self): self.assertTrue(self.m())

    def test_same_count_wrong_keys_rejected(self):
        wrong = dict(self.cj, per_date={f"x{i}": {} for i in range(115)}); self.assertEqual(len(wrong["per_date"]), 115)
        self.assertTrue(RP.probe_cache_reusable(wrong, *self.win, 29, "EPSG:4326", 115))              # the count-only rule accepted this (the demonstrated gap)
        self.assertFalse(self.m(wrong))

    def test_one_swapped_key_missing_or_extra_rejected(self):
        pd_ = dict(self.cj["per_date"]); pd_.pop(self.dates[10]); pd_["2021-12-31"] = {}; self.assertEqual(len(pd_), 115); self.assertFalse(self.m(dict(self.cj, per_date=pd_)))
        self.assertFalse(self.m(expected=self.dates[:-1] + ["2021-12-01"]))

    def test_probe_script_passes_expected_dates(self):
        src = (ROOT / "scripts" / "probe_chirps_coverage.py").read_text(encoding="utf-8"); self.assertIn("expected_dates=[d.isoformat() for d in expected]", src)

    def test_earlier_cache_rules_still_apply(self):
        self.assertFalse(self.m(dict(self.cj, aoi_fingerprint="z"))); self.assertFalse(self.m(dict(self.cj, window=["2021-08-07", "2021-11-28"]))); self.assertFalse(self.m(dict(self.cj, cells_touching_aoi=30)))


class TestProcessExitCodes(unittest.TestCase):
    """Run the scripts as real subprocesses: the guard's return value must become the process exit code."""
    def sub(self, script, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], capture_output=True, text=True, cwd=str(ROOT), timeout=120)

    def test_workflow_reserved_status_id_exits_nonzero_without_side_effects(self):
        reg = status.STATUS_FILE; before = hashlib.sha256(reg.read_bytes()).hexdigest() if reg.exists() else None
        for extra in ((), ("--status-id", "C2"), ("--status-id", "CH3"), ("--status-id", "CH3A"), ("--status-id", "CH3P")):
            with tempfile.TemporaryDirectory() as d:
                d = Path(d); r = self.sub("rainfall_workflow.py", "--source-id", "chirps_2021", "--event", "2021_sep_nov", "--input-dir", str(d / "in"), "--out-dir", str(d / "proc"), "--outputs-dir", str(d / "o"), *extra)
                self.assertEqual(r.returncode, 2, (extra, r.stdout, r.stderr)); self.assertIn("status id isolation", r.stdout)
                self.assertEqual(list(d.iterdir()), [], extra)                                              # nothing created (no in/, proc/, o/)
        self.assertEqual(hashlib.sha256(reg.read_bytes()).hexdigest() if reg.exists() else None, before)    # the real status registry untouched

    def test_snapshot_refusal_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d) / "b.json"; snap.write_text("ORIGINAL")
            r = self.sub("chirps_preservation_check.py", "--snapshot", str(snap), "--root", d); self.assertEqual(r.returncode, 2); self.assertIn("REFUSED", r.stdout); self.assertEqual(snap.read_text(), "ORIGINAL")

    def test_entry_points_propagate_main_return_code(self):
        for n in ("rainfall_workflow", "probe_chirps_coverage", "fetch_chirps_rainfall", "prepare_chirps_rainfall", "chirps_preservation_check"):
            src = (ROOT / "scripts" / f"{n}.py").read_text(encoding="utf-8").rstrip().splitlines()
            self.assertTrue(src[-1].strip() in ("raise SystemExit(main() or 0)", "sys.exit(main() or 0)", "sys.exit(main())"), (n, src[-1]))


if __name__ == "__main__":
    unittest.main()
