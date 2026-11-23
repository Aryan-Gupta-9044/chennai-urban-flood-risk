"""V2.3 window-scan logic tests on SYNTHETIC rows (no Earth Engine; the live scan itself is untested until run)."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.flood_detection import s1_window as W

REF = {"pass": "DESCENDING", "rel_orbit": 92, "platform": "SENTINEL-1A", "angle_mean": 39.0}
def item(**k):
    d = {"id": "x", "mode": "IW", "pols": ["VV", "VH"], "pass": "DESCENDING", "rel_orbit": 92, "platform": "SENTINEL-1A",
         "coverage_pct": 100.0, "valid_pct": 99.0, "angle_mean": 39.2}
    d.update(k); return d

class T(unittest.TestCase):
    def test_compatible(self): self.assertEqual(W.classify(item(), REF)[0], "COMPATIBLE")
    def test_other_orbit(self): self.assertTrue(W.classify(item(rel_orbit=19), REF)[0].startswith("DIFFERENT"))
    def test_ascending(self): self.assertTrue(W.classify(item(**{"pass": "ASCENDING"}), REF)[0].startswith("DIFFERENT"))
    def test_other_platform(self): self.assertTrue(W.classify(item(platform="SENTINEL-1B"), REF)[0].startswith("DIFFERENT"))
    def test_angle(self): self.assertTrue(W.classify(item(angle_mean=42.0), REF)[0].startswith("DIFFERENT"))
    def test_low_coverage(self): self.assertEqual(W.classify(item(coverage_pct=60), REF)[0], "SAME GEOMETRY BUT UNUSABLE")
    def test_no_vv(self): self.assertEqual(W.classify(item(pols=["HH"]), REF)[0], "SAME GEOMETRY BUT UNUSABLE")
    def test_missing_stats(self): self.assertEqual(W.classify(item(valid_pct=None), REF)[0], "SAME GEOMETRY BUT UNUSABLE")
    def test_cycle_dates(self):
        self.assertEqual(W.expected_cycle_dates("2015-11-12", "2015-11-20", "2015-12-20"), ["2015-11-24", "2015-12-06", "2015-12-18"])
        self.assertEqual(W.expected_cycle_dates("2015-11-12", "2015-11-12", "2015-11-12"), ["2015-11-12"])
    def test_derived_rel(self):
        self.assertEqual(W.derived_rel("S1A_IW_GRDH_1SDV_20151112T003120_20151112T003149_008564_00C241_37E8"), 92)

if __name__ == "__main__": unittest.main()
