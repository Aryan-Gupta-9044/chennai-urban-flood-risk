"""IMD file helper + conversion tests (V2.3 demo). Files are SYNTHETIC and built from IMD's DOCUMENTED structure (135x129, 6.5N/66.5E origin,
south-to-north rows, UNDEF -999, daily records). The REAL IMD NetCDF structure has NOT been inspected (download blocked in the build sandbox):
real-file tests must be added/confirmed after the first real run (see outputs/reports/imd_inspection_2015.md)."""
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import rasterio
from scipy.io import netcdf_file
from src.geospatial import imd
from src.utils import status

NY, NX = imd.NY, imd.NX
LAT = imd.LAT0 + 0.25 * np.arange(NY); LON = imd.LON0 + 0.25 * np.arange(NX)
ROW_CHENNAI_S2N = int(round((13.0 - 6.5) / 0.25)); COL_CHENNAI = int(round((80.25 - 66.5) / 0.25))


def make_cube(n=365):
    d, r, c = np.meshgrid(np.arange(n), np.arange(NY), np.arange(NX), indexing="ij")
    cube = ((d % 40) + r * 0.01 + c * 0.0001).astype("float32")          # south-to-north rows, recognisable pattern
    cube[:, 0:5, 0:5] = imd.UNDEF                                          # undefined block in the south-west
    if n > 20:
        cube[10, ROW_CHENNAI_S2N, COL_CHENNAI] = imd.UNDEF                 # one Chennai cell undefined on day 10
        cube[20, 3, 50] = -2.0                                             # a negative value (flag, do not hide)
    return cube


def write_grd(path, cube, order="<f4"):
    Path(path).write_bytes(cube.astype(order).tobytes())


def write_nc(path, cube, lat=LAT, lon=LON, units="days since 2015-01-01 00:00:00", tunits=True, rain_units="mm", fill=imd.UNDEF, upper=True):
    f = netcdf_file(path, "w")
    T = "TIME" if upper else "time"; Y = "LAT" if upper else "lat"; X = "LON" if upper else "lon"
    f.createDimension(T, cube.shape[0]); f.createDimension(Y, len(lat)); f.createDimension(X, len(lon))
    t = f.createVariable(T, "d", (T,)); t[:] = np.arange(cube.shape[0], dtype="float64")
    if tunits: t.units = units
    la = f.createVariable(Y, "f", (Y,)); la[:] = lat.astype("float32"); la.units = "degrees_north"
    lo = f.createVariable(X, "f", (X,)); lo[:] = lon.astype("float32"); lo.units = "degrees_east"
    v = f.createVariable("RAINFALL" if upper else "rf", "f", (T, Y, X)); v[:] = cube
    if rain_units: v.units = rain_units
    if fill is not None: v.missing_value = np.float32(fill)
    f.close()


class TestHelpers(unittest.TestCase):
    def test_expected_sizes(self):
        self.assertEqual(imd.expected_grd_bytes(2015), 365 * 129 * 135 * 4)
        self.assertEqual(imd.expected_grd_bytes(2016), 366 * 129 * 135 * 4)

    def test_grd_roundtrip_undef_to_nan_and_byte_order(self):
        cube = make_cube()
        with tempfile.TemporaryDirectory() as d:
            for order in ("<f4", ">f4"):
                p = Path(d) / f"x{order[0] == '<'}.grd"; write_grd(p, cube, order)
                a, info = imd.read_grd(p, 2015)
                self.assertEqual(info["byte_order"], order); self.assertEqual(a.shape, (365, NY, NX))
                self.assertTrue(np.isnan(a[:, 0:5, 0:5]).all())
                self.assertEqual(float(a[3, 50, 50]), float(cube[3, 50, 50]))
                self.assertEqual(float(a[20, 3, 50]), -2.0)                       # negative kept (flagged later), not hidden or zeroed
            bad = Path(d) / "short.grd"; bad.write_bytes(b"\0" * 1000)
            with self.assertRaises(ValueError): imd.read_grd(bad, 2015)
            leap = Path(d) / "leap.grd"; write_grd(leap, make_cube(365))
            with self.assertRaises(ValueError): imd.read_grd(leap, 2016)          # 365 records in a leap year -> refused

    def test_grid_from_coords(self):
        asc, tr = imd.grid_from_coords(LAT, LON)
        self.assertTrue(asc); self.assertEqual((tr.a, tr.e), (0.25, -0.25)); self.assertAlmostEqual(tr.c, 66.375); self.assertAlmostEqual(tr.f, 38.625)
        asc2, tr2 = imd.grid_from_coords(LAT[::-1], LON); self.assertFalse(asc2); self.assertEqual(tr, tr2)
        asc3, tr3 = imd.grid_from_coords(LAT, LON, "corner"); self.assertAlmostEqual(tr3.c, 66.5)
        with self.assertRaises(ValueError): imd.grid_from_coords(LAT[:-1], LON)
        with self.assertRaises(ValueError): imd.grid_from_coords(LAT + 0.1, LON)       # extent differs from IMD's documentation
        with self.assertRaises(ValueError): imd.grid_from_coords(LAT, LON[::-1])

    def test_chennai_cells(self):
        _, tr = imd.grid_from_coords(LAT, LON)
        cells = imd.cells_for_bounds(tr, (NY, NX), (80.134, 12.852, 80.333, 13.235))
        self.assertEqual(len(cells), 3)
        self.assertTrue(all(abs(c[2] - 80.25) < 1e-9 for c in cells)); self.assertEqual(sorted(round(c[3], 2) for c in cells), [12.75, 13.0, 13.25])

    def test_decode_time(self):
        ds, _ = imd.decode_time([0, 1, 364], "days since 2015-01-01 00:00:00")
        self.assertEqual((ds[0], ds[1], ds[2]), (date(2015, 1, 1), date(2015, 1, 2), date(2015, 12, 31)))
        ds, _ = imd.decode_time([0, 24, 48], "hours since 2015-12-01"); self.assertEqual(ds[2], date(2015, 12, 3))
        with self.assertRaises(ValueError): imd.decode_time([0], None)
        with self.assertRaises(ValueError): imd.decode_time([0], "seconds from epoch")

    def test_clean_values(self):
        a = np.array([1.0, -999.0, 1e20, np.nan, 0.0])
        out, n = imd.clean_values(a, {"missing_value": np.float32(1e20)})
        self.assertEqual(n, 3); self.assertEqual(float(out[0]), 1.0); self.assertEqual(float(out[4]), 0.0)             # real zero preserved
        self.assertTrue(np.isnan(out[[1, 2, 3]]).all())
        out2, _ = imd.clean_values(np.array([10.0, 20.0]), {"scale_factor": 0.1, "add_offset": 1.0}); self.assertTrue(np.allclose(out2, [2.0, 3.0]))

    def test_nc_inspection_names_and_failures(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.nc"; write_nc(p, make_cube(5))
            vs, ga, backend = imd.open_nc(p); inf = imd.inspect_nc(vs, ga)
            self.assertEqual((inf["rain_var"], inf["time_var"], inf["lat_var"], inf["lon_var"]), ("RAINFALL", "TIME", "LAT", "LON"))
            p2 = Path(d) / "b.nc"; write_nc(p2, make_cube(5), upper=False)
            vs, ga, _ = imd.open_nc(p2); inf = imd.inspect_nc(vs, ga); self.assertEqual((inf["rain_var"], inf["lat_var"]), ("rf", "lat"))

    def test_day_definition_is_provisional_and_not_utc(self):
        self.assertIn("PROVISIONAL", imd.DAY_DEFINITION); self.assertIn("08:30 IST", imd.DAY_DEFINITION); self.assertNotIn("UTC calendar", imd.DAY_DEFINITION)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class TestConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prep = load("prepare_imd_rainfall")

    def run_prep(self, d, raw, *extra):
        old_f, old_a = status.STATUS_FILE, sys.argv
        status.STATUS_FILE = Path(d) / "status.json"
        base = Path(d) / "imd"
        sys.argv = ["x", "--raw", str(raw), "--base-dir", str(base), "--outputs-dir", str(Path(d) / "out"), *extra]
        try:
            with mock.patch("src.geospatial.study_area.bounds_wgs84", return_value=(80.134, 12.852, 80.333, 13.235)):
                self.prep.main()
        finally:
            status.STATUS_FILE, sys.argv = old_f, old_a
        return base, json.loads((Path(d) / "status.json").read_text())["modules"]["IMD"]

    def check_outputs(self, d, base, st):
        self.assertEqual(st["state"], "PARTIALLY COMPLETED", st["message"])          # provisional day definition keeps it partial
        tifs = sorted((base / "daily").glob("*.tif")); self.assertEqual(len(tifs), 153)       # 21 Jul .. 20 Dec
        self.assertEqual(tifs[0].name, "20150721.tif"); self.assertEqual(tifs[-1].name, "20151220.tif")
        with rasterio.open(base / "daily" / "20150801.tif") as ds:
            a = ds.read(1)
            self.assertEqual(ds.crs.to_epsg(), 4326); self.assertEqual(ds.res, (0.25, 0.25)); self.assertEqual(ds.shape, (NY, NX))   # native, not resampled
            self.assertAlmostEqual(ds.transform.c, 66.375); self.assertAlmostEqual(ds.transform.f, 38.625)
            doy = (date(2015, 8, 1) - date(2015, 1, 1)).days
            row_n = NY - 1 - ROW_CHENNAI_S2N
            self.assertAlmostEqual(float(a[row_n, COL_CHENNAI]), (doy % 40) + ROW_CHENNAI_S2N * 0.01 + COL_CHENNAI * 0.0001, places=3)   # correct orientation
            self.assertTrue((a[NY - 5:, 0:5] == -9999.0).all())                       # undefined SW block stays nodata, not 0
        src = json.loads((base / "source.json").read_text())
        self.assertIn("PROVISIONAL", src["day_definition"]); self.assertNotIn("UTC calendar", src["day_definition"]); self.assertEqual(src["native_resolution"], "0.25 deg")
        rep = (Path(d) / "out" / "reports" / "imd_inspection_2015.md").read_text()
        self.assertIn("overlap 3 native cell", rep); self.assertIn("completed-day antecedent", rep); self.assertIn("match", rep); self.assertNotIn("MISMATCH", rep)

    def test_grd_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "imd_rain_0p25_2015.grd"; write_grd(raw, make_cube())
            base, st = self.run_prep(d, raw); self.check_outputs(d, base, st)

    def test_nc_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "imd_rain_0p25_2015.nc"; write_nc(raw, make_cube())
            base, st = self.run_prep(d, raw); self.check_outputs(d, base, st)

    def test_nc_descending_latitude(self):
        with tempfile.TemporaryDirectory() as d:
            cube = make_cube()[:, ::-1, :]
            raw = Path(d) / "x.nc"; write_nc(raw, cube, lat=LAT[::-1]); base, st = self.run_prep(d, raw); self.check_outputs(d, base, st)

    def test_nan_preserved_in_chennai_cell(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "x.grd"; write_grd(raw, make_cube())
            base, st = self.run_prep(d, raw, "--all-days")
            day10 = date(2015, 1, 11)                                              # day index 10
            with rasterio.open(base / "daily" / f"{day10:%Y%m%d}.tif") as ds:
                self.assertEqual(float(ds.read(1)[NY - 1 - ROW_CHENNAI_S2N, COL_CHENNAI]), -9999.0)
            self.assertEqual(len(list((base / "daily").glob("*.tif"))), 365)
            import pandas as pd
            df = pd.read_csv(Path(d) / "out" / "tables" / "imd_conversion_2015.csv")
            self.assertEqual(int(df["negative_cells"].sum()), 1); self.assertGreater(int(df["nan_cells"].sum()), 0)

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "a.nc"; write_nc(raw, make_cube(), tunits=False)
            self.assertEqual(self.run_prep(d, raw)[1]["state"], "BLOCKED")           # no time units: dates not guessed
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "a.nc"; write_nc(raw, make_cube(), rain_units="inches")
            st = self.run_prep(d, raw)[1]; self.assertEqual(st["state"], "BLOCKED"); self.assertIn("unit", st["message"])
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "a.nc"; write_nc(raw, make_cube(364))
            st = self.run_prep(d, raw)[1]; self.assertEqual(st["state"], "BLOCKED"); self.assertIn("364", st["message"])      # missing day
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "a.nc"; write_nc(raw, make_cube(), lat=LAT + 1.0)
            self.assertEqual(self.run_prep(d, raw)[1]["state"], "BLOCKED")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_prep(d, Path(d) / "missing.nc")[1]["state"], "BLOCKED")

    def test_original_file_untouched_and_workflow_runs_on_output(self):
        import hashlib
        wf = load("rainfall_workflow")
        import geopandas as gpd
        from shapely.geometry import box
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "x.grd"; write_grd(raw, make_cube()); h = hashlib.sha256(raw.read_bytes()).hexdigest()
            base, st = self.run_prep(d, raw)
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), h)
            sa = gpd.GeoDataFrame(geometry=[box(80.134, 12.852, 80.333, 13.235)], crs=4326)
            old_f, old_a = status.STATUS_FILE, sys.argv
            status.STATUS_FILE = Path(d) / "status2.json"
            sys.argv = ["x", "--source-id", "imd_gridded_daily", "--input-dir", str(base), "--out-dir", str(Path(d) / "proc"), "--outputs-dir", str(Path(d) / "out2")]
            try:
                with mock.patch("src.geospatial.study_area.load_study_area", return_value=(sa, sa, {})), \
                     mock.patch("src.geospatial.study_area.bounds_wgs84", return_value=(80.134, 12.852, 80.333, 13.235)):
                    wf.main()
            finally:
                status.STATUS_FILE, sys.argv = old_f, old_a
            s2 = json.loads((Path(d) / "status2.json").read_text())["modules"]["C2"]
            self.assertEqual(s2["state"], "PARTIALLY COMPLETED", s2["message"])        # provisional day definition
            self.assertIn("event total computed", s2["message"].lower().replace("event total computed", "event total computed"))
            with rasterio.open(Path(d) / "proc" / "imd_gridded_daily" / "2015_nov_dec_event_total_mm_native.tif") as ds:
                self.assertEqual(ds.res, (0.25, 0.25))

if __name__ == "__main__":
    unittest.main()
