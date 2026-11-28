"""Focused tests for S1WC-2 (library + CLI run()): additive class 8, regression against S1WC-1, NoData, TWI clamp, safeguards, manifest hashes. Synthetic data only."""
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
import numpy as np
import pandas as pd


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


T1 = _load("t1_water_candidates_tests", ROOT / "tests" / "test_s1_water_candidates.py")
S2 = _load("s1_water_candidates_v2_review", ROOT / "scripts" / "s1_water_candidates_v2_review.py")
from src.flood_detection import s1_water_candidates as wc, s1_water_candidates_v2 as w2
from src.geospatial.grid import write_raster
GRID, INSIDE, DATES, AOI, NODATA = T1.GRID, T1.INSIDE, T1.DATES, T1.AOI, T1.NODATA
PERSIST, TRANS, ISOL, STEEP = T1.PERSIST, T1.TRANS, T1.ISOL, T1.STEEP
ZERO_T = (slice(4, 8), slice(14, 16))          # DEM == 0 under half of the transient patch
NODATA_T = (slice(6, 8), slice(16, 18))        # DEM NoData under part of the transient patch
PLAT = (slice(28, 32), slice(14, 18))          # dark on date 5, constant DEM 7.5 (16 cells) and slope 0
ZERO_P = (slice(4, 6), slice(4, 8))            # DEM == 0 under part of the persistent patch
CFG2 = json.loads((ROOT / "config" / "s1_water_candidates_v2.json").read_text(encoding="utf-8"))


def lib_dem(shape):
    return 5.0 + 0.01 * np.arange(shape[0] * shape[1], dtype="float64").reshape(shape)       # all-distinct values: no accidental plateaus


class TestLibrary(unittest.TestCase):
    def test_zero_flagged_regardless_of_size_and_slope_irrelevant(self):
        d = lib_dem((8, 8)); d[0, 0] = 0.0; ins = np.ones((8, 8), bool); z, p, s = w2.plateau_signature(d, ins, 30); self.assertTrue(z[0, 0] and s[0, 0] and not p.any()); self.assertEqual(int(s.sum()), 1)

    def test_plateau_size_boundary(self):
        d = lib_dem((10, 10)); d[2:5, 2:5] = 7.0; d[7:9, 0:5] = 9.5       # 9 cells and 10 cells
        ins = np.ones((10, 10), bool); _, p, _ = w2.plateau_signature(d, ins, 10); self.assertTrue(p[7:9, 0:5].all()); self.assertFalse(p[2:5, 2:5].any())
        _, p9, _ = w2.plateau_signature(d, ins, 9); self.assertTrue(p9[2:5, 2:5].all()); _, p11, _ = w2.plateau_signature(d, ins, 11); self.assertFalse(p11.any())

    def test_plateau_is_4_neighbour_only(self):
        d = lib_dem((8, 8)); idx = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]
        for i, j in idx: d[i, j] = 3.0
        _, p, _ = w2.plateau_signature(d, np.ones((8, 8), bool), 2); self.assertFalse(p.any())                      # diagonal chain does not join

    def test_negative_plateau_flagged_and_equal_values_in_two_places_do_not_merge(self):
        d = lib_dem((12, 12)); d[0:3, 0:4] = -1.5; d[8:11, 8:12] = -1.5
        _, p, _ = w2.plateau_signature(d, np.ones((12, 12), bool), 12); self.assertTrue(p[0:3, 0:4].all() and p[8:11, 8:12].all())
        _, p13, _ = w2.plateau_signature(d, np.ones((12, 12), bool), 13); self.assertFalse(p13.any())

    def test_nodata_nan_and_outside_never_flagged_or_joined(self):
        d = lib_dem((8, 8)); d[0:4, 0:2] = 4.0; d[1, 1] = NODATA; d[3, 0] = np.nan; ins = np.ones((8, 8), bool); ins[0, 0:2] = False
        z, p, s = w2.plateau_signature(d, ins, 3); self.assertFalse(s[1, 1] or s[3, 0] or s[0, 0] or s[0, 1]); self.assertFalse(z.any())
        d2 = lib_dem((6, 6)); d2[0, :] = NODATA; z2, p2, s2 = w2.plateau_signature(d2, np.ones((6, 6), bool), 2); self.assertFalse(s2.any())          # NoData row equal to itself must not be a plateau

    def test_flat_terrain_with_slope_zero_but_distinct_dem_is_not_flagged(self):
        d = lib_dem((6, 6)); _, _, s = w2.plateau_signature(d, np.ones((6, 6), bool), 4); self.assertFalse(s.any())

    def test_apply_signature_only_touches_class1(self):
        c = np.array([[0, 1, 1, 2, 3, 4, 5, 6, 7, 254, 255]], "uint8"); sig = np.ones(c.shape, bool); o = w2.apply_signature(c, sig)
        self.assertEqual(o[0].tolist(), [0, 8, 8, 2, 3, 4, 5, 6, 7, 254, 255]); self.assertTrue((w2.fold_back(o) == c).all())
        self.assertTrue((w2.apply_signature(c, np.zeros(c.shape, bool)) == c).all())

    def test_class_names_and_codes(self):
        self.assertEqual(w2.WATER_SIG, 8); self.assertIn("provisional", w2.CLASS_NAMES[8]); self.assertIn("NOT a confirmed water mask", w2.CLASS_NAMES[8]); self.assertEqual({k: v for k, v in w2.CLASS_NAMES.items() if k != 8}, wc.CLASS_NAMES)

    def test_twi_clamp_flags_slope_below_threshold_and_checks_consistency(self):
        slope = np.array([[0.0, 0.05, 0.1, 2.0, NODATA]]); acc = np.full((1, 5), 3.0); expect = np.log(3.0 * 30 / np.tan(np.radians(0.1)))
        twi = np.array([[expect, expect, np.log(3 * 30 / np.tan(np.radians(0.1))), 5.0, 4.0]]); cl, bad = w2.twi_clamp(slope, twi, acc, 30.0, np.ones((1, 5), bool), 0.1)
        self.assertEqual(cl[0].tolist(), [True, True, False, False, False]); self.assertEqual(bad, 0)
        twi2 = twi.copy(); twi2[0, 1] = 1.0; self.assertEqual(w2.twi_clamp(slope, twi2, acc, 30.0, np.ones((1, 5), bool), 0.1)[1], 1)
        cl3, _ = w2.twi_clamp(slope, np.where(np.arange(5) == 0, NODATA, twi), acc, 30.0, np.ones((1, 5), bool), 0.1); self.assertFalse(cl3[0, 0])          # NoData TWI never 'clamped'

    def test_terrain_stats_clamp_excluded_variant(self):
        lay = {"slope_deg": np.array([[0.0, 0.0, 3.0, 4.0]]), "twi": np.array([[9.7, 9.7, 6.0, 7.0]]), "dem_elevation_m": np.array([[1.0, 1.0, 5.0, 6.0]])}; g = {"g": np.array([[True, True, True, False]])}; ref = np.ones((1, 4), bool)
        rows = pd.DataFrame(w2.terrain_stats(lay, g, ref, np.array([[True, True, False, False]]))); a = rows[(rows.variant == "all cells") & (rows.layer == "twi") & (rows.group == "g")].iloc[0]; b = rows[(rows.variant == "clamp-excluded") & (rows.layer == "twi") & (rows.group == "g")].iloc[0]
        self.assertEqual((a.n_cells, a.p50), (3, 9.7)); self.assertEqual((b.n_cells, b.p50), (1, 6.0)); self.assertFalse(((rows.variant == "clamp-excluded") & (rows.layer == "dem_elevation_m")).any())

    def test_block_uniformity_detects_patchy_offset_and_vv_vh(self):
        h = w = 60; vv = np.full((3, h, w), -10.0); vv[2, :30, :] += 3.0; ok = np.ones((3, h, w), bool); rows = w2.block_uniformity(["a", "b", "c"], vv, ok, block=30, min_cells=300)     # per-pixel median over 3 dates = base value
        self.assertAlmostEqual(rows[0]["block_sd_db"], 0.0, places=6); self.assertAlmostEqual(rows[1]["block_sd_db"], 0.0, places=6); self.assertAlmostEqual(rows[2]["block_sd_db"], 1.5, places=6); self.assertEqual(rows[2]["frac_blocks_within_1db"], 0.0)      # block medians 3.0 and 0.0, reference = their median 1.5, both >1 dB away
        vh = vv - 8.0; r = w2.vv_vh_stable(["a", "b", "c"], vv, vh, ok); self.assertAlmostEqual(r[0]["stable_vv_minus_vh_db"], 8.0)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.indir = T1.write_inputs(self.tmp / "in"); self.refd = self.tmp / "ref"; self.refd.mkdir(); self.assertTrue(INSIDE[PLAT].all())
        import rasterio
        for pol in ("VV", "VH"):                                                                   # add a plateau-shaped dark patch on date index 5 (2021-11-04)
            p = self.indir / f"S1A_IW_D092_{DATES[T1.BRIGHT_DATE].replace('-', '')}_{pol}_dB.tif"; a = rasterio.open(p).read(1); a[PLAT] = -22.0 if pol == "VV" else -28.0; write_raster(p, a, GRID, NODATA, "t", "float32")
        dem = lib_dem(GRID.shape); dem[PLAT] = 7.5; dem[ZERO_T] = 0.0; dem[ZERO_P] = 0.0; dem[NODATA_T] = NODATA; dem[~INSIDE] = NODATA
        slope = np.full(GRID.shape, 1.0); slope[STEEP] = 10.0; slope[PLAT] = 0.0; slope[ZERO_T] = 0.0
        acc = np.full(GRID.shape, 3.0); twi = np.log(acc * 30.0 / np.tan(np.radians(np.maximum(slope, 0.1))))
        for n, a in (("dem", dem), ("slope", slope), ("twi", twi), ("acc", acc)): write_raster(self.refd / f"{n}.tif", a.astype("float32"), GRID, NODATA, "t", "float32")
        self.cfg1 = copy.deepcopy(T1.CFG0); self.cfg1["reference_layers"] = {"slope_deg": str(self.refd / "slope.tif")}
        self.cfg2 = copy.deepcopy(CFG2); self.cfg2["reference_layers"] = {"dem_elevation_m": str(self.refd / "dem.tif"), "slope_deg": str(self.refd / "slope.tif"), "twi": str(self.refd / "twi.tif"), "flow_accumulation": str(self.refd / "acc.tif")}
        self.cfg2["v2_params"] = {**self.cfg2["v2_params"], "min_plateau_cells": 10}; self.s1dir = self.tmp / "outputs" / "s1wc1_out"; self.out = self.tmp / "outputs" / "wc2"
        rc, info = T1.S.run(self.indir, self.s1dir, self.cfg1, GRID, AOI, self.tmp, None, DATES); self.assertEqual(rc, 0, info)

    def go(self, outdir=None, s1dir="default", cfg2=None, indir=None, shared=(), allow=False, dates=None):
        return S2.run(indir or self.indir, outdir or self.out, cfg2 or self.cfg2, self.cfg1, GRID, AOI, self.tmp, dates or DATES, shared_dirs=shared, allow_missing_metadata=allow, s1wc1_dir=(self.s1dir if s1dir == "default" else s1dir))

    def cls(self, d, out=None):
        import rasterio
        return rasterio.open((out or self.out) / "rasters" / f"s1_water_candidates_v2_class_{d}.tif").read(1)


def tree_hash(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


class TestRun(Base):
    def test_class8_assignment_and_counts(self):
        rc, info = self.go(); self.assertEqual(rc, 0, info); d5 = DATES[T1.BRIGHT_DATE]; c = self.cls(d5)
        self.assertTrue((c[ZERO_T] == 8).all()); self.assertTrue((c[PLAT] == 8).all()); self.assertTrue((c[(slice(4, 8), slice(16, 18))] == 1).all())      # NoData DEM stays class 1; unflagged half stays class 1
        self.assertTrue((c[NODATA_T] == 1).all()); self.assertTrue((c[PERSIST] == 2).all()); self.assertTrue((c[ISOL] == 4).all()); self.assertTrue((c[STEEP] == 3).all()); self.assertTrue((c[~INSIDE] == 255).all())          # persistent on zero DEM remains 2
        ba = pd.read_csv(self.out / "tables" / "s1_water_candidates_v2_before_after_counts_per_date.csv").set_index("date_utc"); r = ba.loc[d5]
        self.assertEqual((int(r.s1wc1_class1_candidates), int(r.s2_class1_candidates_remaining), int(r.s2_class8_on_dem_signature)), (32, 8, 24)); self.assertTrue(ba.class1_plus_class8_equals_s1wc1.all())
        for d in DATES:
            if d != d5: self.assertEqual(int(ba.loc[d].s2_class8_on_dem_signature), 0)

    def test_regression_v2_folded_equals_s1wc1_and_s1wc1_outputs_unchanged(self):
        h = tree_hash(self.s1dir); rc, info = self.go(); self.assertEqual(rc, 0, info); self.assertEqual(tree_hash(self.s1dir), h)
        import rasterio
        for d in DATES:
            v1 = rasterio.open(self.s1dir / "rasters" / f"s1_water_candidates_class_{d}.tif").read(1); v2 = self.cls(d); self.assertTrue((w2.fold_back(v2) == v1).all(), d); self.assertTrue((v2[(v2 != 8)] == v1[v2 != 8]).all())
        reg = pd.read_csv(self.out / "tables" / "s1_water_candidates_v2_regression_vs_s1wc1.csv"); self.assertTrue(reg.v2_folded_equals_s1wc1_recomputed.all() and reg.recomputed_equals_stored_s1wc1.all()); self.assertEqual(len(info["s1wc1_compared"]), 8)

    def test_tampered_s1wc1_raster_stops_run(self):
        p = self.s1dir / "rasters" / f"s1_water_candidates_class_{DATES[0]}.tif"; a = __import__("rasterio").open(p).read(1); a[INSIDE] = 0; write_raster(p, a, GRID, 255, "t", "uint8"); rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("differ from the stored S1WC-1" in s for s in i["stops"])); self.assertFalse(self.out.exists())

    def test_s1wc1_dir_missing_recomputes_and_says_so(self):
        rc, info = self.go(s1dir=self.tmp / "nope"); self.assertEqual(rc, 0, info); self.assertIn("none (the S1WC-1 output directory was not available", (self.out / "reports" / "s1_water_candidates_v2_report.md").read_text(encoding="utf-8"))

    def test_signature_raster_and_label(self):
        self.assertEqual(self.go()[0], 0); import rasterio
        s = rasterio.open(self.out / "rasters" / "s1_water_candidates_v2_dem_water_signature.tif").read(1); self.assertTrue((s[ZERO_T] == 1).all() and (s[PLAT] == 2).all() and (s[NODATA_T] == 0).all() and (s[~INSIDE] == 255).all())
        sm = pd.read_csv(self.out / "tables" / "s1_water_candidates_v2_dem_signature_summary.csv"); self.assertTrue(sm.value.astype(str).str.contains("NOT a confirmed permanent-water mask").any()); self.assertTrue(sm.value.astype(str).str.contains("WBM NOT used").any())
        self.assertEqual(int(sm[sm.quantity == "slope == 0 & DEM > 0 cells NOT flagged (flat terrain without the plateau signature)"].value.iloc[0]), 0)

    def test_twi_clamp_table_and_missing_twi(self):
        self.assertEqual(self.go()[0], 0); t = pd.read_csv(self.out / "tables" / "s1_water_candidates_v2_twi_clamp_summary.csv").set_index("quantity").value
        self.assertEqual(int(t["stored-TWI vs clamp-formula consistency failures among clamped cells"]), 0); self.assertGreater(int(t["clamped AOI cells (slope < clamp)"]), 0)
        ts = pd.read_csv(self.out / "tables" / "s1_water_candidates_v2_terrain_context.csv"); self.assertIn("clamp-excluded", set(ts.variant))
        cfg = copy.deepcopy(self.cfg2); del cfg["reference_layers"]["twi"]; rc, i = self.go(outdir=self.tmp / "outputs" / "wc2b", cfg2=cfg); self.assertEqual(rc, 0, i)
        self.assertIn("skipped", pd.read_csv(self.tmp / "outputs" / "wc2b" / "tables" / "s1_water_candidates_v2_twi_clamp_summary.csv").value.iloc[0])

    def test_comparability_table_next_to_counts(self):
        self.assertEqual(self.go()[0], 0); c = pd.read_csv(self.out / "tables" / "s1_water_candidates_v2_comparability_with_counts.csv")
        for col in ("s1wc1_class1_candidates", "s2_class8_on_dem_signature", "vv_stable_minus_mean_of_dates_db", "vh_stable_minus_mean_of_dates_db", "stable_vv_minus_vh_db", "vv_block_sd_db", "vv_frac_blocks_within_1db"): self.assertIn(col, c.columns)
        self.assertEqual(len(c), 8); self.assertTrue(c.interpretation_note.str.contains("NOT comparable").all())

    def test_manifest_output_hashes_caveats_and_parameters_unchanged(self):
        self.assertEqual(self.go()[0], 0); man = json.loads((self.out / "reports" / "s1_water_candidates_v2_manifest.json").read_text()); self.assertTrue(man["input_hashes_unchanged"]); self.assertFalse(man["status_json_modified"])
        outs = {k: Path(v) for k, v in man["outputs"].items()}; self.assertEqual(set(man["output_sha256"]), set(outs))
        for k, p in outs.items(): self.assertEqual(man["output_sha256"][k], hashlib.sha256(p.read_bytes()).hexdigest(), k)
        self.assertEqual(man["s1wc1_parameters_reused"], self.cfg1["params"]); self.assertTrue(any("Water Body Mask" in c or "WBM" in c for c in man["caveats"])); self.assertTrue(any("TWI" in c for c in man["caveats"])); self.assertTrue(any("flattens water" in c for c in man["caveats"]))
        rep = (self.out / "reports" / "s1_water_candidates_v2_report.md").read_text(encoding="utf-8"); self.assertIn("NOT VALIDATED", rep); self.assertIn("not confirmed floodwater", rep); self.assertIn("not** the Copernicus Water Body Mask", rep)
        for bad in ("normalis" + "ed to", "F1", "IoU", "recall"):
            self.assertNotIn(bad, rep.replace("no accuracy, precision, recall, F1 or IoU", "").replace("no accuracy, precision, recall, F1 or IoU;", ""))

    def test_reproducible_byte_identical_rasters(self):
        self.assertEqual(self.go()[0], 0); a = tree_hash(self.out / "rasters"); o2 = self.tmp / "outputs" / "wc2c"; self.assertEqual(self.go(outdir=o2)[0], 0); self.assertEqual({k: v for k, v in tree_hash(o2 / "rasters").items()}, a)

    def test_output_safeguards(self):
        self.assertEqual(self.go()[0], 0); h = tree_hash(self.out); rc, i = self.go(); self.assertEqual(rc, 2); self.assertIn("existing outputs", i["stops"][0]); self.assertEqual(tree_hash(self.out), h)
        for bad in (self.s1dir, self.s1dir / "sub", self.tmp / "outputs", self.indir / "sub"):
            rc, i = self.go(outdir=bad); self.assertEqual(rc, 2, str(bad))
        pr = self.tmp / "s1_water_candidates_review_v1_copy" / "x"; rc, i = self.go(outdir=pr); self.assertEqual(rc, 2); self.assertIn("protected", i["stops"][0]); self.assertFalse(pr.exists())
        sh = self.tmp / "shared"; (sh / "reports").mkdir(parents=True); rc, i = self.go(outdir=sh / "reports" / "z", shared=(sh / "reports",)); self.assertEqual(rc, 2)

    def test_missing_dem_stops_and_nothing_written(self):
        (self.refd / "dem.tif").unlink(); rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("dem_elevation_m" in s for s in i["stops"])); self.assertFalse(self.out.exists())

    def test_dem_grid_mismatch_refused_no_resampling(self):
        import geopandas as gpd
        from shapely.geometry import box
        from src.geospatial.grid import make_master_grid
        other = make_master_grid(gpd.GeoSeries([box(80.18, 13.00, 80.195, 13.012)], crs=4326).to_crs(32644).total_bounds); write_raster(self.refd / "dem.tif", np.ones(other.shape, "float32"), other, NODATA, "t", "float32")
        rc, i = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("no resampling" in s for s in i["stops"])); self.assertFalse(self.out.exists())

    def test_metadata_policy_and_date_handling(self):
        for f in self.indir.glob("*_meta.json"): f.unlink()
        rc, i = self.go(); self.assertEqual(rc, 2); rc, i = self.go(allow=True, outdir=self.tmp / "outputs" / "wc2d"); self.assertEqual(rc, 0, i)
        for bad in (["2021-9-05"], ["2021-02-30"], ["2021-09-05", "2021-09-05"]): self.assertEqual(self.go(dates=bad, outdir=self.tmp / "outputs" / f"d{abs(hash(str(bad)))}")[0], 2)

    def test_input_changed_during_run_is_rc3(self):
        real = S2.sp.sha256_file; n = {"c": 0}; target = str(self.refd / "dem.tif")

        def h(p):
            if str(p) == target:
                n["c"] += 1
                if n["c"] == 2: return "0" * 64
            return real(p)
        S2.sp.sha256_file = h
        try: rc, i = self.go()
        finally: S2.sp.sha256_file = real
        self.assertEqual(rc, 3); self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
