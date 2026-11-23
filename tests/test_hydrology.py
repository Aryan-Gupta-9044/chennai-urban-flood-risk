"""Hydrology tests (V2.3). SYNTHETIC rasters only - they test the algorithms and file metadata, not Chennai data or hydrological truth."""
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from src.geospatial import hydrology as H
from src.geospatial.terrain import slope_degrees
from src.utils import status

TR = from_origin(400000, 1430000, 30, 30)


def run(z, valid=None, max_fill=1.0):
    valid = np.ones(z.shape, bool) if valid is None else valid
    cond, info = H.condition_dem(z.astype("float64"), valid, max_fill)
    fd = H.d8_flow_direction(cond, valid)
    acc = H.flow_accumulation(fd)
    return cond, info, fd, acc, valid


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class TestCore(unittest.TestCase):
    def test_flat_surface_drains_to_edge_and_conserves(self):
        z = np.full((20, 20), 5.0)
        cond, info, fd, acc, valid = run(z)
        self.assertEqual(info["n_depressions"], 0)
        interior = ~H.outlet_mask(valid)
        self.assertTrue((fd[interior] > 0).all() and (fd[interior] != 255).all())      # every interior cell has a direction
        self.assertEqual(np.nansum(acc[H.terminal_cells(fd)]), 400)
        self.assertTrue(np.nanmax(acc) >= 2)
        self.assertTrue(np.array_equal(z, np.full((20, 20), 5.0)))                      # input untouched

    def test_simple_slope_east(self):
        z = np.tile(np.arange(10, 0, -1, dtype=float), (6, 1))        # falls to the east
        cond, info, fd, acc, valid = run(z)
        self.assertTrue((fd[:, :-1] == 1).all())                       # E
        self.assertTrue((acc[:, -1] == 10).all())                      # each row's 10 cells reach the last column
        self.assertEqual(np.nansum(acc[:, -1]), 60)

    def test_single_drainage_path_v_valley(self):
        r, c = np.mgrid[0:11, 0:11]
        z = np.abs(c - 5) * 2.0 + (10 - r) * 0.1       # valley along column 5, falling southwards
        cond, info, fd, acc, valid = run(z)
        self.assertEqual(int(acc[10, 5]), int(np.nanmax(acc)))
        self.assertTrue((fd[1:10, 5] == 4).all())                      # S along the thalweg
        net = H.extract_drainage(acc, 8)
        self.assertTrue(net[5:, 5].all() and not net[:, 0].any())
        self.assertEqual(np.nansum(acc[H.terminal_cells(fd)]), 121)

    def test_small_depression_filled_deep_kept(self):
        z = np.tile(np.arange(20, 0, -1, dtype=float), (20, 1)) * 0.1
        z[8:11, 8:11] -= 0.4                                           # shallow pit
        cond, info, fd, acc, valid = run(z, max_fill=1.0)
        self.assertEqual((info["n_filled"], info["n_kept"]), (1, 0))
        self.assertTrue((cond[8:11, 8:11] >= 0.9).all() and (cond[8:11, 8:11] < 0.9 + 1e-4).all())   # filled to the spill level
        z2 = z.copy(); z2[4:7, 4:7] -= 3.0                             # deep pit
        cond2, info2, fd2, acc2, _ = run(z2, max_fill=1.0)
        self.assertEqual(info2["n_kept"], 1)
        self.assertTrue(np.array_equal(cond2[4:7, 4:7], z2[4:7, 4:7]))  # deep depression NOT filled
        sinks = H.terminal_cells(fd2) & ~H.outlet_mask(valid)
        self.assertGreaterEqual(int(sinks.sum()), 1)                     # internal sink present, flow stops there
        self.assertEqual(np.nansum(acc2[H.terminal_cells(fd2)]), 400)
        cond3, info3, *_ = run(z2, max_fill=10.0)
        self.assertEqual(info3["n_kept"], 0)                             # generous limit fills it

    def test_nodata_boundaries_and_disconnected_area(self):
        z = np.tile(np.arange(30, 0, -1, dtype=float), (12, 1))
        valid = np.ones(z.shape, bool)
        valid[:, 14:16] = False                                          # a NoData wall splits the raster
        valid[0:3, 0:3] = False
        cond, info, fd, acc, _ = run(z, valid)
        self.assertTrue((fd[~valid] == 255).all()); self.assertTrue(np.isnan(acc[~valid]).all())
        tgt = H.downstream_index(fd)
        ok = tgt >= 0
        self.assertTrue(valid.ravel()[tgt[ok]].all())                    # never flows into NoData
        self.assertEqual(np.nansum(acc[H.terminal_cells(fd)]), int(valid.sum()))
        self.assertTrue(np.nanmax(acc[:, :14]) <= int(valid[:, :14].sum()))   # nothing crosses the wall

    def test_accumulation_matches_bruteforce(self):
        rng = np.random.default_rng(3)
        z = rng.normal(0, 1, (25, 25)).cumsum(0) * 0.2 + rng.random((25, 25))
        valid = rng.random((25, 25)) > 0.05
        cond, info, fd, acc, _ = run(z, valid)
        tgt = H.downstream_index(fd).reshape(-1)
        N = tgt.size
        up = {}
        for i in range(N):
            if tgt[i] >= 0:
                up.setdefault(int(tgt[i]), []).append(i)
        def count(i, seen=None):
            return 1 + sum(count(j) for j in up.get(i, []))
        import sys as _s; _s.setrecursionlimit(10000)
        for i in np.flatnonzero(valid.ravel())[::37]:
            self.assertEqual(count(int(i)), int(acc.ravel()[i]))

    def test_threshold_logic(self):
        self.assertEqual(H.threshold_from(30, threshold_km2=0.09)[0], 100)
        self.assertEqual(H.threshold_from(30, threshold_cells=50, threshold_km2=5)[0], 50)
        self.assertEqual(H.threshold_from(30)[0], int(np.ceil(0.1 / 0.0009)))
        with self.assertRaises(ValueError): H.threshold_from(30, threshold_cells=0)
        r, c = np.mgrid[0:30, 0:30]
        cond, info, fd, acc, valid = run(np.abs(c - 15) * 1.0 + (30 - r) * 0.05)
        prev = None
        for t in (2, 10, 30, 100):
            n = H.extract_drainage(acc, t)
            if prev is not None: self.assertTrue((n & ~prev).sum() == 0)   # higher threshold -> subset
            prev = n
        self.assertGreater(H.extract_drainage(acc, 2).sum(), H.extract_drainage(acc, 100).sum())

    def test_twi_zero_slope_stable(self):
        acc = np.full((4, 4), 10.0); slope = np.zeros((4, 4)); slope[0, 0] = np.nan
        t, frac = H.twi(acc, slope, 30)
        self.assertTrue(np.isfinite(t[1:, :]).all() and np.isnan(t[0, 0]))
        self.assertAlmostEqual(frac, 15 / 15)
        t2, f2 = H.twi(acc, np.full((4, 4), 5.0), 30)
        self.assertAlmostEqual(float(t2[0, 0]), float(np.log(300 / np.tan(np.radians(5)))), places=4); self.assertEqual(f2, 0.0)

    def test_negative_cluster_diagnostics(self):
        z = np.tile(np.arange(30, 0, -1, dtype=float), (30, 1)) * 0.3 + 2.0
        z[10:13, 10:13] = -2.0
        valid = np.ones(z.shape, bool)
        cond, info = H.condition_dem(z, valid, 1.0)
        rows, s = H.negative_clusters(z, valid, info, 30, TR)
        self.assertEqual((s["negative_cells"], s["clusters"]), (9, 1))
        self.assertTrue(rows[0]["closed_depression"] and rows[0]["kept_unfilled"])
        self.assertIn("UNVERIFIED", rows[0]["interpretation"])

    def test_validate_dem_errors(self):
        z = np.zeros((5, 5))
        with self.assertRaises(ValueError): H.validate_dem(z, TR, CRS.from_epsg(4326), -9999)
        with self.assertRaises(ValueError): H.validate_dem(z, TR, CRS.from_epsg(32643), -9999)
        with self.assertRaises(ValueError): H.validate_dem(z, from_origin(0, 0, 30, 20), CRS.from_epsg(32644), -9999)
        with self.assertRaises(ValueError): H.validate_dem(np.full((5, 5), -9999.0), TR, CRS.from_epsg(32644), -9999)
        f, v = H.validate_dem(z, TR, CRS.from_epsg(32644), -9999); self.assertEqual(f["valid_cells"], 25)

    def test_reproducible(self):
        rng = np.random.default_rng(1)
        z = rng.random((40, 40)) + np.linspace(3, 0, 40)
        a = run(z); b = run(z)
        for i in (0, 2, 3):
            self.assertTrue(np.array_equal(a[i], b[i], equal_nan=True))


class TestScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("hyd_script", ROOT / "scripts" / "process_hydrology.py")
        cls.mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.mod)

    def make_dem(self, d, epsg=32644, nodata=-9999.0):
        rng = np.random.default_rng(7)
        r, c = np.mgrid[0:60, 0:60]
        z = (60 - c) * 0.12 + np.abs(r - 30) * 0.05 + rng.normal(0, 0.02, (60, 60))
        z[20:24, 20:24] -= 2.5
        z[0:5, 0:5] = nodata
        p = Path(d) / "dem.tif"
        with rasterio.open(p, "w", driver="GTiff", height=60, width=60, count=1, dtype="float32", crs=CRS.from_epsg(epsg), transform=TR, nodata=nodata) as ds:
            ds.write(z.astype("float32"), 1)
        sl = slope_degrees(np.where(z == nodata, nodata, z).astype("float64"), 30, nodata)
        sp = Path(d) / "slope.tif"
        with rasterio.open(sp, "w", driver="GTiff", height=60, width=60, count=1, dtype="float32", crs=CRS.from_epsg(epsg), transform=TR, nodata=nodata) as ds:
            ds.write(sl, 1)
        return p, sp

    def run_cli(self, d, dem, slope, *extra):
        out, odir = Path(d) / "proc", Path(d) / "outputs"
        old_f, old_argv = status.STATUS_FILE, sys.argv
        status.STATUS_FILE = Path(d) / "status.json"
        sys.argv = ["x", "--dem", str(dem), "--slope", str(slope), "--out-dir", str(out), "--outputs-dir", str(odir),
                    "--threshold-cells", "20", *extra]
        try:
            self.mod.main()
        finally:
            status.STATUS_FILE, sys.argv = old_f, old_argv
        return out, odir, None

    def test_end_to_end_synthetic(self):
        with tempfile.TemporaryDirectory() as d:
            dem, sp = self.make_dem(d); h0 = sha(dem)
            out, odir, _ = self.run_cli(d, dem, sp)
            self.assertEqual(sha(dem), h0)                                   # original DEM untouched
            for n in ("dem_conditioned", "flow_direction_d8", "flow_accumulation", "drainage_network"):
                p = out / f"{n}_utm44n_30m.tif"
                self.assertTrue(p.exists(), n)
                with rasterio.open(p) as ds:
                    self.assertEqual(ds.crs.to_epsg(), 32644); self.assertEqual(ds.transform, TR); self.assertEqual(ds.shape, (60, 60))
            with rasterio.open(out / "flow_direction_d8_utm44n_30m.tif") as ds:
                fd = ds.read(1); self.assertEqual(ds.dtypes[0], "uint8"); self.assertTrue((fd[0:5, 0:5] == 255).all())
            with rasterio.open(out / "flow_accumulation_utm44n_30m.tif") as ds:
                acc = ds.read(1); self.assertTrue((acc[0:5, 0:5] == -9999).all()); self.assertGreater(acc.max(), 100)
            with rasterio.open(out / "dem_conditioned_utm44n_30m.tif") as ds:
                self.assertEqual(ds.dtypes[0], "float64")
            for f in ("tables/hydrology_statistics.csv", "tables/hydrology_negative_clusters.csv", "reports/hydrology_methodology.md",
                      "figures/flow_accumulation_map.png", "figures/drainage_network_map.png", "figures/dem_conditioning_difference.png"):
                self.assertTrue((odir / f).exists(), f)
            txt = (odir / "reports" / "hydrology_methodology.md").read_text()
            self.assertIn("UNVERIFIED", txt); self.assertIn("NOT stormwater infrastructure", txt.replace("not stormwater infrastructure", "NOT stormwater infrastructure"))
            self.assertIn("**True**", txt)
            import json
            s = json.loads((Path(d) / "status.json").read_text())["modules"]["HYD"]
            self.assertIn(s["state"], ("COMPLETED", "PARTIALLY COMPLETED"))

    def test_reproducible_outputs(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            dem, sp = self.make_dem(d1)
            o1, *_ = self.run_cli(d1, dem, sp)
            o2, *_ = self.run_cli(d2, dem, sp)
            for n in ("dem_conditioned", "flow_direction_d8", "flow_accumulation", "drainage_network"):
                with rasterio.open(o1 / f"{n}_utm44n_30m.tif") as a, rasterio.open(o2 / f"{n}_utm44n_30m.tif") as b:
                    self.assertTrue(np.array_equal(a.read(1), b.read(1)))

    def test_wrong_crs_blocked_and_no_outputs(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            dem, sp = self.make_dem(d, epsg=32643)
            out, *_ = self.run_cli(d, dem, sp)
            s = json.loads((Path(d) / "status.json").read_text())["modules"]["HYD"]
            self.assertEqual(s["state"], "BLOCKED"); self.assertIn("EPSG", s["message"])
            self.assertFalse((out / "flow_accumulation_utm44n_30m.tif").exists())

    def test_missing_dem_blocked(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            self.run_cli(d, Path(d) / "nope.tif", Path(d) / "s.tif")
            self.assertEqual(json.loads((Path(d) / "status.json").read_text())["modules"]["HYD"]["state"], "BLOCKED")

    def test_refuses_to_overwrite_input(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            dem, sp = self.make_dem(d)
            target = Path(d) / "proc"; target.mkdir()
            # the DEM sits where the conditioned DEM would be written
            clash = target / "dem_conditioned_utm44n_30m.tif"; clash.write_bytes(dem.read_bytes()); h = sha(clash)
            old_f, old_argv = status.STATUS_FILE, sys.argv
            status.STATUS_FILE = Path(d) / "status.json"
            sys.argv = ["x", "--dem", str(clash), "--slope", str(sp), "--out-dir", str(target), "--outputs-dir", str(Path(d) / "o")]
            try:
                self.mod.main()
            finally:
                status.STATUS_FILE, sys.argv = old_f, old_argv
            self.assertEqual(sha(clash), h)
            self.assertEqual(json.loads((Path(d) / "status.json").read_text())["modules"]["HYD"]["state"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
