"""V2 unit tests. Inputs are tiny hand-made structures used ONLY to test logic (not flood observations)."""
import sys, unittest, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src.flood_detection import s1_catalog as cat
from src.flood_detection.agreement import agreement


def sc(d, direction, orbit, cov=100.0):
    return {"scene": f"{direction[0]}{orbit}_{d}", "date": d, "time_utc": d + "T00:30:00Z", "platform": "Sentinel-1A",
            "direction": direction, "rel_orbit": orbit, "polarization": "VV+VH", "coverage_pct": cov}


class T(unittest.TestCase):
    def test_pairing_same_orbit_only(self):
        scenes = [sc("2021-10-20", "ASCENDING", 150), sc("2021-10-26", "ASCENDING", 150), sc("2021-11-01", "ASCENDING", 150),
                  sc("2021-11-13", "DESCENDING", 33),               # post exists only on ANOTHER orbit
                  sc("2021-11-16", "ASCENDING", 150)]
        r = cat.pair_scenes(scenes, ("2021-10-10", "2021-11-04"), ("2021-11-11", "2021-11-24"), "2021-11-11")
        self.assertEqual(r["verdict"], "PROCESSABLE")
        self.assertEqual(r["orbit"], {"direction": "ASCENDING", "rel_orbit": 150})
        self.assertEqual(r["days_after_peak"], 5)

    def test_not_processable_when_orbits_differ(self):
        scenes = [sc("2023-11-10", "ASCENDING", 150), sc("2023-12-06", "DESCENDING", 33)]
        r = cat.pair_scenes(scenes, ("2023-10-20", "2023-11-30"), ("2023-12-04", "2023-12-14"), "2023-12-04")
        self.assertEqual(r["verdict"], "NOT PROCESSABLE")

    def test_marginal_weak_baseline_or_late(self):
        scenes = [sc("2023-11-10", "ASCENDING", 150), sc("2023-12-13", "ASCENDING", 150)]
        r = cat.pair_scenes(scenes, ("2023-10-20", "2023-11-30"), ("2023-12-04", "2023-12-14"), "2023-12-04")
        self.assertEqual(r["verdict"], "MARGINAL")
        self.assertIn("weak baseline", r["reason"])

    def test_partial_coverage_scene_ignored(self):
        scenes = [sc("2021-10-20", "ASCENDING", 150, 40.0), sc("2021-11-16", "ASCENDING", 150)]
        r = cat.pair_scenes(scenes, ("2021-10-10", "2021-11-04"), ("2021-11-11", "2021-11-24"), "2021-11-11")
        self.assertEqual(r["verdict"], "NOT PROCESSABLE")

    def test_asf_normalise_both_shapes(self):
        rec = {"granuleName": "S1A_X", "startTime": "2021-11-16T00:30:00Z", "platform": "Sentinel-1A",
               "flightDirection": "ASCENDING", "pathNumber": 150, "polarization": "VV+VH",
               "stringFootprint": "POLYGON((79 12,81 12,81 14,79 14,79 12))"}
        for raw in ([[rec]], [rec]):
            out = cat.normalise(raw, (80.1, 12.8, 80.4, 13.3))
            self.assertEqual(out[0]["rel_orbit"], 150)
            self.assertEqual(out[0]["coverage_pct"], 100.0)

    def test_agreement(self):
        d = np.array([[1, 1, 0, 0]]); r = np.array([[1, 0, 1, 0]])
        m = agreement(d, r)
        self.assertEqual((m["tp"], m["fp"], m["fn"], m["tn"]), (1, 1, 1, 1))
        self.assertAlmostEqual(m["iou"], 1 / 3)

    def test_read_bounds_projected_raster(self):
        import rasterio
        from rasterio.transform import from_origin
        from src.geospatial.raster_io import read_bounds
        p = os.path.join(tempfile.mkdtemp(), "utm.tif")
        with rasterio.open(p, "w", driver="GTiff", height=1500, width=1000, count=1, dtype="float32", crs="EPSG:32644",
                           transform=from_origin(400000, 1470000, 30, 30)) as o:
            o.write(np.ones((1500, 1000), "float32"), 1)
        r = read_bounds(p, (80.14, 12.85, 80.33, 13.24))
        self.assertIsNotNone(r)  # V1 returned None here (bug fixed in V2)


if __name__ == "__main__":
    unittest.main()
