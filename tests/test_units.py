"""Unit tests on tiny synthetic arrays (test logic only; no project data is simulated)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src.geospatial.terrain import slope_degrees
from src.geospatial.grid import make_master_grid
from src.flood_detection.change_detection import detect_flood_change


class T(unittest.TestCase):
    def test_slope_plane(self):
        x = np.arange(20, dtype="float64")[None, :].repeat(20, 0) * 30 * np.tan(np.radians(10))
        s = slope_degrees(x.astype("float32"), 30.0)
        self.assertAlmostEqual(float(s[10, 10]), 10.0, places=2)

    def test_slope_nodata(self):
        d = np.full((5, 5), -9999.0, dtype="float32")
        self.assertTrue((slope_degrees(d, 30.0) == -9999.0).all())

    def test_grid_snapping(self):
        g = make_master_grid((500010, 1430020, 530000, 1470000), 30.0, 32644, pad_cells=0)
        self.assertEqual(g.transform.c % 30, 0)
        self.assertEqual(g.transform.f % 30, 0)
        self.assertGreaterEqual(g.width * 30, 530000 - 500010)

    def test_change_detection(self):
        pre = np.array([[-8.0, -8.0, -20.0, np.nan]])
        post = np.array([[-20.0, -9.0, -21.0, -20.0]])
        out = detect_flood_change(pre, post)
        self.assertEqual(out.tolist(), [[1, 0, 0, 255]])  # only strong drop + dark = flood; permanent water not flagged
        slope = np.array([[10.0, 0, 0, 0]])
        self.assertEqual(detect_flood_change(pre, post, slope_deg=slope)[0, 0], 0)  # steep slope masked


if __name__ == "__main__":
    unittest.main()
