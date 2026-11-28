"""Focused tests for the Sentinel-1 per-date dark-backscatter candidate review product (library + CLI run()). Synthetic data only."""
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from src.flood_detection import s1_water_candidates as wc, s1_inventory as inv
from src.geospatial.grid import make_master_grid, write_raster, inside_mask

DATES = ["2021-09-05", "2021-09-17", "2021-09-29", "2021-10-11", "2021-10-23", "2021-11-04", "2021-11-16", "2021-11-28"]
AOI = box(80.18, 13.00, 80.19, 13.01)
GRID = make_master_grid(gpd.GeoSeries([AOI], crs=4326).to_crs(32644).total_bounds)
INSIDE = inside_mask(GRID, [gpd.GeoSeries([AOI], crs=4326).to_crs(GRID.crs).iloc[0]])
FP = inv.query_fingerprint(AOI)[0][:12]
CFG0 = json.loads((ROOT / "config" / "s1_water_candidates.json").read_text(encoding="utf-8"))
NODATA = -9999.0
PERSIST = (slice(4, 8), slice(4, 8))            # dark all 8 dates
TRANS = (slice(4, 8), slice(14, 18))            # dark on date index 5 only (4x4)
ISOL = (slice(14, 15), slice(4, 5))             # single dark cell on date 5 -> small cluster
VVONLY = (slice(14, 18), slice(14, 18))         # VV dark, VH not, date 5
STEEP = (slice(22, 26), slice(4, 8))            # dark on date 5 but slope 10 deg
NODPATCH = (slice(22, 24), slice(14, 16))       # NoData on dates 2, 3
BRIGHT_DATE = 5


def load_script():
    spec = importlib.util.spec_from_file_location("s1_water_candidates_review", ROOT / "scripts" / "s1_water_candidates_review.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


S = load_script()


def synth():
    rng = np.random.default_rng(5); vv, vh, vf = {}, {}, {}
    for i, d in enumerate(DATES):
        a = -12 + rng.normal(0, 0.3, GRID.shape); b = -19 + rng.normal(0, 0.3, GRID.shape); f = np.ones(GRID.shape, "float32")
        a[PERSIST], b[PERSIST] = -22, -28
        if i == BRIGHT_DATE:
            a[TRANS], b[TRANS] = -22, -28; a[ISOL], b[ISOL] = -22, -28; a[VVONLY] = -22; a[STEEP], b[STEEP] = -22, -28
        if i in (2, 3): a[NODPATCH] = NODATA; b[NODPATCH] = NODATA; f[NODPATCH] = 0.0
        vv[d], vh[d], vf[d] = a, b, f
    return vv, vh, vf


def write_inputs(indir, fp=FP, status="QA_PASS", meta=True):
    indir = Path(indir); indir.mkdir(parents=True, exist_ok=True); vv, vh, vf = synth()
    for d in DATES:
        for pol, arr in (("VV", vv[d]), ("VH", vh[d])):
            v = (arr != NODATA) & (vf[d] >= 0.5); stem = f"S1A_IW_D092_{d.replace('-', '')}_{pol}"
            write_raster(indir / f"{stem}_dB.tif", np.where(v, arr, NODATA).astype("float32"), GRID, NODATA, "t", "float32")
            write_raster(indir / f"{stem}_validfrac.tif", vf[d], GRID, None, "t", "float32"); write_raster(indir / f"{stem}_valid.tif", v.astype("uint8"), GRID, None, "t", "uint8")
        if meta: (indir / f"S1A_IW_D092_{d.replace('-', '')}_meta.json").write_text(json.dumps({"date_utc": d, "status": status, "aoi_fingerprint": fp}))
    return indir


def tree_hash(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


class TestLibrary(unittest.TestCase):
    def test_valid_pol_requires_all_conditions_and_never_zero_fills(self):
        db = np.array([-20.0, NODATA, np.nan, -20.0, -20.0]); vf = np.array([1, 1, 1, .4, 1.0]); fl = np.array([1, 1, 1, 1, 0])
        self.assertEqual(wc.valid_pol(db, vf, fl, 0.5).tolist(), [True, False, False, False, False])

    def test_dark_requires_both_pols_and_invalid_is_never_dark(self):
        vv = np.array([-20, -20, -10, -20.0]); vh = np.array([-26, -20, -26, -26.0]); ok = np.array([1, 1, 1, 0], bool)
        self.assertEqual(wc.dark_mask(vv, vh, -18, -24, ok).tolist(), [True, False, False, False]); self.assertEqual(wc.vv_only_dark(vv, vh, -18, -24, ok).tolist(), [False, True, False, False])
        self.assertFalse(wc.dark_mask(np.array([-30.0]), np.array([-30.0]), -18, -24, np.array([False])).any())

    def test_threshold_is_strict_less_than(self):
        self.assertFalse(wc.dark_mask(np.array([-18.0]), np.array([-30.0]), -18, -24, np.array([True])).any())

    def test_persistence_boundaries_and_unassessable(self):
        d = np.zeros((8, 1, 4), bool); v = np.ones((8, 1, 4), bool); d[:6, 0, 0] = True; d[:5, 0, 1] = True; v[:3, 0, 2] = False; d[:, 0, 2] = True; v[:, 0, 3] = False
        nd, nv, pers, assess = wc.persistence(d, v, 6, 6)
        self.assertEqual(pers[0].tolist(), [True, False, False, False]); self.assertEqual(assess[0].tolist(), [True, True, False, False]); self.assertEqual(nv[0].tolist(), [8, 8, 5, 0])
        self.assertFalse(pers[0, 2])                                                                                       # not assessable never counts as persistent

    def test_cluster_keep_is_8_neighbour(self):
        m = np.zeros((6, 6), bool); m[0, 0] = m[1, 1] = m[2, 2] = m[3, 3] = True; m[5, 5] = True
        k, r = wc.cluster_keep(m, 4); self.assertEqual(int(k.sum()), 4); self.assertTrue(r[5, 5]); k1, r1 = wc.cluster_keep(m, 1); self.assertTrue((k1 == m).all() and not r1.any())

    def test_classify_precedence_and_unknowns(self):
        n = 6; inside = np.array([[1, 1, 1, 1, 1, 0]], bool); valid = np.array([[1, 0, 1, 1, 1, 1]], bool)
        dark = np.array([[1, 0, 1, 1, 1, 1]], bool); vonly = np.zeros((1, n), bool); pers = np.array([[0, 0, 0, 0, 0, 0]], bool); assess = np.ones((1, n), bool)
        slope = np.array([[1.0, 1.0, np.nan, 10.0, 1.0, 1.0]])
        c = wc.classify_date(valid, dark, vonly, pers, assess, slope, inside, 5.0, 1)
        self.assertEqual(c[0].tolist(), [wc.TRANSIENT, wc.INVALID, wc.TERRAIN_UNKNOWN, wc.TERRAIN, wc.TRANSIENT, wc.OUTSIDE])
        c2 = wc.classify_date(valid, dark, vonly, np.array([[1, 0, 0, 0, 0, 0]], bool), assess, slope, inside, 5.0, 1); self.assertEqual(c2[0, 0], wc.PERSISTENT)
        c3 = wc.classify_date(valid, dark, vonly, pers, np.zeros((1, n), bool), slope, inside, 5.0, 1); self.assertEqual(c3[0, 0], wc.UNASSESSED)
        self.assertEqual(wc.classify_date(valid, np.zeros((1, n), bool), vonly, pers, assess, slope, inside, 5.0, 1)[0, 0], wc.NOT_DARK)
        c4 = wc.classify_date(valid, dark, vonly, pers, assess, np.full((1, n), wc.NODATA), inside, 5.0, 1); self.assertEqual(c4[0, 0], wc.TERRAIN_UNKNOWN)   # NoData slope is unknown, never 0

    def test_invalid_never_becomes_not_dark(self):
        valid = np.zeros((2, 2), bool); c = wc.classify_date(valid, valid, valid, valid, valid, np.ones((2, 2)), np.ones((2, 2), bool), 5, 1); self.assertTrue((c == wc.INVALID).all())

    def test_date_count_and_outside(self):
        st = np.array([[[wc.TRANSIENT, 0]], [[wc.TRANSIENT, 0]]], "uint8"); out = wc.date_count(st, wc.TRANSIENT, np.array([[True, False]])); self.assertEqual(out.tolist(), [[2, 255]])

    def test_radiometric_shift_flags_offset_without_correcting(self):
        vv = np.full((3, 4, 4), -12.0); vv[1] -= 2.0; vh = vv - 7; ok = np.ones_like(vv, bool); rows = wc.radiometric_shift(["a", "b", "c"], vv, vh, ok)
        self.assertAlmostEqual(rows[1]["median_vv_stable_db"], -14.0); self.assertAlmostEqual(rows[0]["median_vv_stable_db"], -12.0); self.assertEqual(rows[0]["stable_cells"], 16)

    def test_sensitivity_rows_cover_grid_and_select_nothing(self):
        r = wc.sensitivity_rows("d", np.full((2, 2), -20.0), np.full((2, 2), -25.0), np.ones((2, 2), bool), 4); self.assertEqual(len(r), 12); self.assertFalse(any("selected" in str(x) for x in r))

    def test_class_counts_sum_to_aoi(self):
        c = np.array([[0, 1, 254, 255]], "uint8"); rows = wc.class_counts(c, 0.0009, 3); self.assertEqual(sum(r["cells"] for r in rows), 3)


class TestWording(unittest.TestCase):
    def test_dark_is_neither_necessary_nor_sufficient_everywhere(self):
        for f in ("src/flood_detection/s1_water_candidates.py", "scripts/s1_water_candidates_review.py", "docs/s1_water_candidates_review.md"):
            t = (ROOT / f).read_text(encoding="utf-8").lower(); self.assertIn("neither necessary nor sufficient", t.replace("neither necessary nor sufficient:", "neither necessary nor sufficient"), f); self.assertNotIn("necessary but not sufficient", t, f)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.indir = write_inputs(self.tmp / "in"); self.out = self.tmp / "outputs" / "wc_v1"
        self.refd = self.tmp / "ref"; self.refd.mkdir(); sl = np.full(GRID.shape, 1.0, "float32"); sl[STEEP] = 10.0
        write_raster(self.refd / "slope.tif", sl, GRID, NODATA, "t", "float32"); self.cfg = copy.deepcopy(CFG0); self.cfg["reference_layers"] = {"slope_deg": str(self.refd / "slope.tif"), "dem_elevation_m": str(self.refd / "absent.tif")}
        self.rain = self.tmp / "rain.csv"; pd.DataFrame([{"s1_date": d, "prior_1d_aoi_mean_mm": float(i)} for i, d in enumerate(DATES)]).to_csv(self.rain, index=False)

    def go(self, outdir=None, indir=None, cfg=None, rain="default", aoi=AOI, dates=None, shared=(), allow=False):
        return S.run(indir or self.indir, outdir or self.out, cfg or self.cfg, GRID, aoi, self.tmp, self.rain if rain == "default" else rain, dates or DATES, shared_dirs=shared, allow_missing_metadata=allow)


class TestRun(Base):
    def test_full_run_classes_and_semantics(self):
        h0 = tree_hash(self.indir); rc, info = self.go(); self.assertEqual(rc, 0, info); self.assertTrue(info["preserved"]); self.assertEqual(tree_hash(self.indir), h0)
        outs = S.planned_outputs(self.out.resolve(), DATES); [self.assertTrue(p.exists(), k) for k, p in outs.items()]
        import rasterio
        def cls(i):
            with rasterio.open(outs[f"ras_class_{DATES[i]}"]) as ds: self.assertEqual(ds.nodata, 255.0); self.assertEqual(ds.dtypes[0], "uint8"); return ds.read(1)
        c5, c0, c2 = cls(5), cls(0), cls(2)
        self.assertTrue((c5[PERSIST] == wc.PERSISTENT).all()); self.assertTrue((c0[PERSIST] == wc.PERSISTENT).all())
        self.assertTrue((c5[TRANS] == wc.TRANSIENT).all()); self.assertTrue((c0[TRANS] == wc.NOT_DARK).all())          # dark on one date only; other dates stay separate
        self.assertTrue((c5[ISOL] == wc.SMALL).all()); self.assertTrue((c5[VVONLY] == wc.VV_ONLY).all()); self.assertTrue((c5[STEEP] == wc.TERRAIN).all())
        self.assertTrue((c2[NODPATCH] == wc.INVALID).all()); self.assertTrue((c5[NODPATCH] == wc.NOT_DARK).all())          # NoData -> invalid, never 'not dark'
        self.assertTrue((c5[~INSIDE] == wc.OUTSIDE).all())
        with rasterio.open(outs["ras_transient_count"]) as ds: tc = ds.read(1)
        self.assertTrue((tc[TRANS] == 1).all()); self.assertTrue((tc[PERSIST] == 0).all()); self.assertTrue((tc[~INSIDE] == 255).all())
        with rasterio.open(outs["ras_n_valid"]) as ds: nv = ds.read(1)
        self.assertEqual(int(nv[NODPATCH].max()), 6); self.assertEqual(int(nv[PERSIST].min()), 8)
        with rasterio.open(outs["ras_persistent"]) as ds: pm = ds.read(1)
        self.assertTrue((pm[PERSIST] == 1).all()); self.assertTrue((pm[TRANS] == 0).all())
        cc = pd.read_csv(outs["class_counts"]); r5 = cc[cc.date_utc == DATES[5]].set_index("class_code")
        self.assertEqual(int(r5.loc[wc.TRANSIENT, "cells"]), 16); self.assertEqual(int(r5.loc[wc.SMALL, "cells"]), 1); self.assertEqual(int(r5.loc[wc.PERSISTENT, "cells"]), 16)
        self.assertEqual(int(r5["cells"].sum()), int(INSIDE.sum()))                                                      # classes partition the AOI
        man = json.loads(outs["manifest"].read_text()); self.assertFalse(man["status_json_modified"]); self.assertIn("not a flood extent", man["claims"]); self.assertIn("NOT an event date", man["date_meaning"])
        rep = outs["report"].read_text(encoding="utf-8"); self.assertIn("NOT VALIDATED", rep); self.assertNotIn("precision", rep.lower().replace("no accuracy, precision", ""))
        self.assertEqual(man["reference_layers_absent"], ["dem_elevation_m"])

    def test_reproducible_byte_identical_rasters(self):
        self.assertEqual(self.go()[0], 0); a = tree_hash(self.out / "rasters"); b_out = self.tmp / "outputs" / "wc_v2"; self.assertEqual(self.go(outdir=b_out)[0], 0)
        b = tree_hash(b_out / "rasters"); self.assertEqual({k.replace("v2", "v1"): v for k, v in b.items()}, a)
        self.assertEqual((self.out / "tables" / "s1_water_candidates_class_counts_per_date.csv").read_bytes(), (b_out / "tables" / "s1_water_candidates_class_counts_per_date.csv").read_bytes())

    def test_no_overwrite_and_nothing_written_on_stop(self):
        self.assertEqual(self.go()[0], 0); h = tree_hash(self.out); rc, info = self.go(); self.assertEqual(rc, 2); self.assertIn("existing outputs", info["stops"][0]); self.assertEqual(tree_hash(self.out), h)

    def test_output_dir_safeguards(self):
        rc, i = self.go(outdir=self.indir / "sub"); self.assertEqual(rc, 2); self.assertIn("overlaps the input", i["stops"][0])
        shared = self.tmp / "outputs"; (shared / "reports").mkdir(parents=True, exist_ok=True)
        for bad in (shared, shared / "reports" / "x", self.tmp):
            rc, i = self.go(outdir=bad, shared=(shared / "reports",)); self.assertEqual(rc, 2, str(bad))
        pr = self.tmp / "s1_2021_persistence_v2" / "x"; rc, i = self.go(outdir=pr); self.assertEqual(rc, 2); self.assertIn("protected", i["stops"][0]); self.assertFalse(pr.exists())

    def test_date_handling(self):
        for bad in (["2021-9-05"], ["2021-02-30"], ["2021-09-05", "2021-09-05"], ["20210905"], []): rc, i = self.go(dates=bad, outdir=self.tmp / "o" / str(abs(hash(str(bad))))) if bad else (2, {"stops": []}); self.assertEqual(rc, 2)
        self.assertEqual(S.parse_dates(["2021-11-04", "2021-09-05"]), ["2021-09-05", "2021-11-04"])

    def test_missing_input_lists_exact_path(self):
        (self.indir / "S1A_IW_D092_20211104_VV_dB.tif").unlink(); rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("20211104_VV_dB.tif" in s for s in i["stops"])); self.assertFalse(self.out.exists())

    def test_missing_slope_stops_instead_of_assuming_flat(self):
        (self.refd / "slope.tif").unlink(); rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("slope_deg" in s for s in i["stops"])); self.assertFalse(self.out.exists())

    def test_reference_grid_mismatch_refused_no_resampling(self):
        other = make_master_grid(gpd.GeoSeries([box(80.18, 13.00, 80.195, 13.012)], crs=4326).to_crs(32644).total_bounds); write_raster(self.refd / "slope.tif", np.ones(other.shape, "float32"), other, NODATA, "t", "float32") if (self.refd / "slope.tif").unlink() is None else None
        rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("no resampling" in s for s in i["stops"])); self.assertFalse(self.out.exists())

    def test_s1_grid_mismatch_refused(self):
        other = make_master_grid(gpd.GeoSeries([box(80.18, 13.00, 80.195, 13.012)], crs=4326).to_crs(32644).total_bounds)
        write_raster(self.indir / "S1A_IW_D092_20210905_VV_dB.tif", np.full(other.shape, -12, "float32"), other, NODATA, "t", "float32"); rc, i = self.go(); self.assertEqual(rc, 2); self.assertFalse(self.out.exists())

    def test_metadata_policy(self):
        for f in self.indir.glob("*_meta.json"): f.unlink()
        rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("metadata" in s for s in i["stops"]))
        rc, i = self.go(allow=True); self.assertEqual(rc, 0); self.assertIn("missing for some dates", (self.out / "reports" / "s1_water_candidates_report.md").read_text())
        self.assertFalse(any(json.loads((self.out / "reports" / "s1_water_candidates_manifest.json").read_text())["metadata_present"].values()))

    def test_non_qa_pass_and_fingerprint_mismatch_refused(self):
        write_inputs(self.indir, status="QA_FAIL"); rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("QA_PASS" in s for s in i["stops"]))
        write_inputs(self.indir); rc, i = self.go(aoi=box(80.0, 12.9, 80.01, 12.91), outdir=self.tmp / "o2"); self.assertEqual(rc, 2); self.assertTrue(any("fingerprint" in s for s in i["stops"]))

    def test_rainfall_is_context_only_and_skippable(self):
        self.assertEqual(self.go()[0], 0); rj = pd.read_csv(self.out / "tables" / "s1_water_candidates_rainfall_join.csv"); self.assertIn("transient_candidate_cells", rj.columns); self.assertNotIn("spearman_rho", rj.columns)
        rc, i = self.go(rain=None, outdir=self.tmp / "o3"); self.assertEqual(rc, 0); self.assertFalse((self.tmp / "o3" / "tables" / "s1_water_candidates_rainfall_join.csv").exists())

    def test_input_changed_during_run_is_rc3(self):
        real = S.sp.sha256_file; n = {"c": 0}; target = str(self.indir / "S1A_IW_D092_20210905_VV_dB.tif")
        def h(p):
            if str(p) == target:
                n["c"] += 1
                if n["c"] == 2: return "0" * 64
            return real(p)
        S.sp.sha256_file = h
        try: rc, i = self.go()
        finally: S.sp.sha256_file = real
        self.assertEqual(rc, 3); self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
