"""S1PE: cross-date bright-VV persistence diagnostic. SYNTHETIC rasters only (no real data, no Earth Engine, no network). Exploratory/descriptive diagnostic; no flood labels."""
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from src.flood_detection import s1_persistence as sp, s1_inventory as inv
from src.geospatial.grid import make_master_grid, write_raster, inside_mask

DATES = ["2021-09-05", "2021-09-17", "2021-09-29", "2021-10-11", "2021-10-23", "2021-11-04", "2021-11-16", "2021-11-28"]
AOI = box(80.18, 13.00, 80.19, 13.01)
GRID = make_master_grid(gpd.GeoSeries([AOI], crs=4326).to_crs(32644).total_bounds)
INSIDE = inside_mask(GRID, [gpd.GeoSeries([AOI], crs=4326).to_crs(GRID.crs).iloc[0]])
FP = inv.query_fingerprint(AOI)[0][:12]


def load_script():
    spec = importlib.util.spec_from_file_location("s1_preprocess_persistence", ROOT / "scripts" / "s1_preprocess_persistence.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


S = load_script()
# synthetic scene design (row/col windows inside the AOI): base VV ~ -12 dB, VH ~ -19 dB
PERSIST = (slice(10, 14), slice(10, 14))        # bright on all 8 dates
RECUR4 = (slice(10, 14), slice(20, 24))         # bright on dates 0,1,5,6   (4 dates)
NOVONLY = (slice(20, 24), slice(10, 14))        # bright on the last 3 dates only (recurrent, not in comparison group)
SINGLE_ = (slice(20, 24), slice(20, 24))        # bright on date 5 only
NODATA_PATCH = (slice(28, 30), slice(28, 30))   # NoData on dates 2 and 3


def synth_arrays():
    rng = np.random.default_rng(11); vv, vh, vf = {}, {}, {}
    for i, d in enumerate(DATES):
        a = -12 + rng.normal(0, 0.3, GRID.shape); b = -19 + rng.normal(0, 0.3, GRID.shape); f = np.ones(GRID.shape, "float32")
        a[PERSIST] = 8.0
        if i in (0, 1, 5, 6): a[RECUR4] = 7.0
        if i in (5, 6, 7): a[NOVONLY] = 9.0
        if i == 5: a[SINGLE_] = 10.0
        if i in (2, 3): a[NODATA_PATCH] = sp.NODATA; b[NODATA_PATCH] = sp.NODATA; f[NODATA_PATCH] = 0.0
        vv[d], vh[d], vf[d] = a, b, f
    return vv, vh, vf


def write_inputs(indir, fp=FP, status="QA_PASS", grid=GRID):
    indir = Path(indir); indir.mkdir(parents=True, exist_ok=True); vv, vh, vf = synth_arrays()
    for d in DATES:
        for pol, arr in (("VV", vv[d]), ("VH", vh[d])):
            v = (arr != sp.NODATA) & (vf[d] >= 0.5); stem = f"S1A_IW_D092_{d.replace('-', '')}_{pol}"
            write_raster(indir / f"{stem}_dB.tif", np.where(v, arr, sp.NODATA).astype("float32"), grid, sp.NODATA, "t", "float32")
            write_raster(indir / f"{stem}_validfrac.tif", vf[d], grid, None, "t", "float32"); write_raster(indir / f"{stem}_valid.tif", v.astype("uint8"), grid, None, "t", "uint8")
        (indir / f"S1A_IW_D092_{d.replace('-', '')}_meta.json").write_text(json.dumps({"date_utc": d, "status": status, "aoi_fingerprint": fp, "output_crs": "EPSG:32644", "output_shape": list(GRID.shape)}))
    return indir


def tree_hash(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


class TestLibrary(unittest.TestCase):
    def test_grid_problems_and_cross_grid(self):
        ok = {"shape": GRID.shape, "crs": GRID.crs, "transform": tuple(GRID.transform)[:6], "count": 1, "dtype": "float32", "nodata": -9999.0}
        self.assertEqual(sp.grid_problems(ok, GRID), [])
        self.assertTrue(any("shape" in x for x in sp.grid_problems(dict(ok, shape=(5, 5)), GRID)))
        self.assertTrue(any("CRS" in x for x in sp.grid_problems(dict(ok, crs="EPSG:4326"), GRID)))
        t = list(ok["transform"]); t[2] += 30.0; self.assertTrue(any("transform" in x for x in sp.grid_problems(dict(ok, transform=tuple(t)), GRID)))
        self.assertTrue(any("bands" in x for x in sp.grid_problems(dict(ok, count=2), GRID)))
        self.assertEqual(sp.cross_grid_problems({"a": ok, "b": dict(ok)}), []); self.assertTrue(sp.cross_grid_problems({"a": ok, "b": dict(ok, shape=(3, 3))}))

    def test_valid_cells_nodata_never_zero_and_outside_excluded(self):
        db = np.array([[-9999.0, 0.0, 5.0, np.nan]]); vf = np.array([[1.0, 1.0, 0.4, 1.0]]); ins = np.array([[True, True, True, True]])
        self.assertEqual(sp.valid_cells(db, vf, ins, 0.5).tolist(), [[False, True, False, False]])                  # 0 dB is a legitimate VALUE; sentinel/NaN/low-fraction are invalid
        self.assertEqual(sp.valid_cells(db, vf, np.array([[True, False, True, True]]), 0.5).tolist(), [[False, False, False, False]])

    def test_persistence_counts_missing_is_not_bright_and_not_valid(self):
        d = ["a", "b", "c"]; dbs = {"a": np.array([6.0, 6.0, 1.0]), "b": np.array([6.0, np.nan, 1.0]), "c": np.array([6.0, 6.0, 1.0])}; val = {k: np.isfinite(v) for k, v in dbs.items()}
        nv, nb = sp.persistence_counts(dbs, val, d, 5.0); self.assertEqual(nv.tolist(), [3, 2, 3]); self.assertEqual(nb.tolist(), [3, 2, 0])
        nv0, nb0 = sp.persistence_counts(dbs, val, d, 0.0); self.assertEqual(nb0.tolist(), [3, 2, 3])

    def test_classify_boundaries_and_sensitivity(self):
        nb = np.arange(0, 9); nv = np.full(9, 8)
        for cut, expect in ((5, [0, 1, 2, 3, 3, 4, 4, 4, 4]), (6, [0, 1, 2, 3, 3, 3, 4, 4, 4]), (7, [0, 1, 2, 3, 3, 3, 3, 4, 4])): self.assertEqual(sp.classify(nb, nv, cut).tolist(), expect, cut)
        self.assertEqual(sp.classify(np.array([6, 6, 5]), np.array([5, 6, 6]), 6).tolist(), [255, 4, 3])              # < 6 valid dates -> not assessed (255), never 'never bright'
        with self.assertRaises(ValueError): sp.classify(nb, nv, 3)

    def test_frequency_is_bright_over_valid(self):
        f = sp.frequency(np.array([3, 6, 4]), np.array([6, 8, 5])); self.assertAlmostEqual(f[0], 0.5); self.assertAlmostEqual(f[1], 0.75); self.assertTrue(np.isnan(f[2]))

    def test_class_counts_and_decomposition(self):
        d = ["a", "b", "c", "d"]; dbs = {k: np.full((1, 4), -10.0) for k in d}; dbs["a"][0, 0] = 9; dbs["b"][0, 0] = 9; dbs["c"][0, 0] = 9; dbs["d"][0, 0] = 9; dbs["d"][0, 1] = 9; dbs["a"][0, 2] = 9
        val = {k: np.ones((1, 4), bool) for k in d}; nv, nb = sp.persistence_counts(dbs, val, d, 5.0); cls = sp.classify(nb, nv, 4, min_valid=4)
        self.assertEqual(cls.tolist(), [[4, 1, 1, 0]]); cc = {r["class"]: r["cells"] for r in sp.class_counts(cls, np.ones((1, 4), bool), nb, nv)}
        self.assertEqual((cc["persistent"], cc["single-date"], cc["never bright"]), (1, 2, 1))
        dec = {r["date_utc"]: r for r in sp.date_decomposition(dbs, val, d, cls, 5.0, d[:2])}
        self.assertEqual((dec["a"]["bright_cells"], dec["a"]["persistent_cells"], dec["a"]["single-date_cells"]), (2, 1, 1)); self.assertEqual(dec["d"]["bright_cells"], 2)
        self.assertEqual(dec["d"]["bright_not_in_other_comparison_dates_cells"], 1)      # cell 1 is bright on d and on neither a nor b; cell 0 is bright on a/b too

    def test_components_8_neighbour_and_area(self):
        m = np.zeros((6, 6), bool); m[1, 1] = m[2, 2] = True; m[4, 4] = True
        rows = sp.components(m, GRID, "x"); self.assertEqual(sorted(r["cells"] for r in rows), [1, 2]); self.assertAlmostEqual(max(r["area_km2"] for r in rows), 2 * 900 / 1e6)
        s = sp.component_summary(rows, "x", 3); self.assertEqual((s["n_components"], s["single_cell_components"], s["largest_component_cells"]), (2, 1, 2)); self.assertEqual(sp.components(np.zeros((3, 3), bool), GRID, "x"), [])

    def test_per_date_stats_and_shift(self):
        db = np.array([[-10.0, 0.0, 10.0, np.nan]]); val = np.isfinite(db); ins = np.ones((1, 4), bool); r = sp.per_date_stats(db, val, ins)
        self.assertEqual((r["aoi_cells"], r["valid_cells"], r["gt5_cells"], r["gt0_cells"]), (4, 3, 1, 1)); self.assertAlmostEqual(r["gt5_pct_of_aoi"], 25.0); self.assertAlmostEqual(r["gt5_pct_of_valid"], 100 / 3, 3)
        self.assertGreater(r["power_mean_db"], r["mean_db"])                                                          # power mean >= dB mean (Jensen)
        base = np.random.default_rng(1).normal(-12, 1, (20, 20)); ds = ["g1", "g2", "x"]; dbs = {"g1": base, "g2": base.copy(), "x": base + 2.0}; vals = {k: np.ones((20, 20), bool) for k in ds}
        rows = {r["date_utc"]: r for r in sp.shift_vs_group(dbs, vals, ds, ["g1", "g2"])}
        self.assertAlmostEqual(rows["x"]["d_p50_db"], 2.0, 3); self.assertAlmostEqual(rows["x"]["paired_median_diff_db"], 2.0, 3); self.assertAlmostEqual(rows["g1"]["paired_median_diff_db"], 0.0, 6); self.assertTrue(rows["g1"]["in_comparison_group"])

    def test_read_rainfall_uses_only_verified_columns_and_skips_on_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"; rows = [{"s1_date": x, "category": "unassigned", "prior_1d_aoi_mean_mm": float(i), "prior_30d_aoi_mean_mm": 10.0 * i} for i, x in enumerate(DATES)]
            pd.DataFrame(rows).to_csv(p, index=False); df, info = sp.read_rainfall(p, DATES)
            self.assertEqual(info["used_columns"], ["prior_1d_aoi_mean_mm", "prior_30d_aoi_mean_mm"]); self.assertEqual(list(df.columns), ["s1_date", "prior_1d_aoi_mean_mm", "prior_30d_aoi_mean_mm"]); self.assertIsNone(info["skipped_reason"])
            pd.DataFrame(rows).assign(prior_3d_aoi_mean_mm=1.0).to_csv(p, index=False); self.assertIn("prior_3d_aoi_mean_mm", sp.read_rainfall(p, DATES)[1]["used_columns"])   # used only because it is present
            pd.DataFrame(rows[:-1]).to_csv(p, index=False); df, info = sp.read_rainfall(p, DATES); self.assertIsNone(df); self.assertIn("dates do not match", info["skipped_reason"])
            pd.DataFrame(rows).drop(columns=["prior_1d_aoi_mean_mm", "prior_30d_aoi_mean_mm"]).to_csv(p, index=False); self.assertIsNone(sp.read_rainfall(p, DATES)[0])
            df, info = sp.read_rainfall(Path(d) / "absent.csv", DATES); self.assertIsNone(df); self.assertEqual(info["skipped_reason"], "file not found")
            rows[2]["prior_1d_aoi_mean_mm"] = np.nan; pd.DataFrame(rows).to_csv(p, index=False); df, _ = sp.read_rainfall(p, DATES); self.assertTrue(np.isnan(df["prior_1d_aoi_mean_mm"].iloc[2]))     # never filled

    def test_spearman_descriptive(self):
        x = pd.DataFrame({"r": [1.0, 2, 3, 4], "m": [1.0, 2, 3, 4], "c": [1.0, 1, 1, 1]}); rows = {(r["rainfall_column"], r["metric"]): r for r in sp.spearman_rows(x, x, ["r"], ["m", "c"])}
        self.assertEqual(rows[("r", "m")]["spearman_rho"], 1.0); self.assertIsNone(rows[("r", "c")]["spearman_rho"]); self.assertIn("descriptive", rows[("r", "m")]["note"])


class TestMainPath(unittest.TestCase):
    """Drives the REAL main() (and a fresh module import) against a temporary project layout; synthetic data only."""
    def setUp(self):
        import shutil
        from src.utils import paths as P, config as UC
        from src.geospatial import study_area as SA
        self.P, self.UC, self.SA = P, UC, SA
        self.root = Path(tempfile.mkdtemp()); cfgd = self.root / "config"; cfgd.mkdir(); proc = self.root / "data" / "processed"; proc.mkdir(parents=True)
        for n in ("s1_preprocess.json", "settings.json"): shutil.copy(ROOT / "config" / n, cfgd / n)
        gpd.GeoDataFrame(geometry=[AOI], crs=4326).to_file(proc / "study_area_wgs84.geojson", driver="GeoJSON")
        gpd.GeoDataFrame(geometry=[AOI], crs=4326).to_crs(32644).to_file(proc / "study_area_utm44n.geojson", driver="GeoJSON")
        (proc / "study_area_meta.json").write_text("{}")
        write_inputs(proc / "s1_2021")
        rd = self.root / "outputs" / "chirps_2021" / "tables"; rd.mkdir(parents=True)
        pd.DataFrame([{"s1_date": d, "category": "unassigned", "prior_1d_aoi_mean_mm": float(i), "prior_30d_aoi_mean_mm": 10.0 * i + 1} for i, d in enumerate(DATES)]).to_csv(rd / "rainfall_chirps_2021_2021_sep_nov_antecedent_before_s1.csv", index=False)
        self.cfgd, self.proc = cfgd, proc
        self.patches = [mock.patch.object(P, "ROOT", self.root), mock.patch.object(P, "CONFIG", cfgd), mock.patch.object(P, "OUT_REP", self.root / "outputs" / "reports"),
                        mock.patch.object(P, "OUT_TAB", self.root / "outputs" / "tables"), mock.patch.object(P, "OUT_FIG", self.root / "outputs" / "figures"), mock.patch.object(UC, "CONFIG", cfgd),
                        mock.patch.object(SA, "WGS", proc / "study_area_wgs84.geojson"), mock.patch.object(SA, "UTM", proc / "study_area_utm44n.geojson"), mock.patch.object(SA, "META", proc / "study_area_meta.json"),
                        mock.patch.object(sys, "argv", ["s1_preprocess_persistence.py"])]
        UC.load_settings.cache_clear()
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)]); self.addCleanup(UC.load_settings.cache_clear)

    def instrumented_main(self, hash_hook=None):
        ev = []; real_hash, real_info, real_loads, real_load, real_rf = sp.sha256_file, S.tif_info, json.loads, json.load, gpd.read_file
        real_lsa, real_mg = S.load_study_area, S.master_grid
        def h(p):
            ev.append(("hash", Path(p).name)); return hash_hook(p, real_hash(p)) if hash_hook else real_hash(p)
        def ti(p): ev.append(("tif_info", Path(p).name)); return real_info(p)
        def jl(*a, **k): ev.append(("json.loads", "")); return real_loads(*a, **k)
        def jld(*a, **k): ev.append(("json.load", "")); return real_load(*a, **k)
        def rf(p, *a, **k): ev.append(("read_file", Path(p).name)); return real_rf(p, *a, **k)
        def lsa(): ev.append(("load_study_area", "")); return real_lsa()
        def mg(): ev.append(("master_grid", "")); return real_mg()
        with mock.patch.object(sp, "sha256_file", h), mock.patch.object(S, "tif_info", ti), mock.patch.object(json, "loads", jl), mock.patch.object(json, "load", jld), \
                mock.patch.object(gpd, "read_file", rf), mock.patch.object(S, "load_study_area", lsa), mock.patch.object(S, "master_grid", mg), mock.patch("builtins.print"):
            rc = S.main()
        return rc, ev

    def test_main_hashes_every_source_before_it_is_parsed_or_loaded(self):
        rc, ev = self.instrumented_main(); self.assertEqual(rc, 0)
        idx = lambda pred: [i for i, e in enumerate(ev) if pred(e)]                                                           # noqa: E731
        first = lambda pred: idx(pred)[0]                                                                                      # noqa: E731
        h = lambda name: first(lambda e: e == ("hash", name))                                                                  # noqa: E731
        # configuration: hashed before the first json.loads (its parse)
        self.assertLess(h("s1_preprocess.json"), first(lambda e: e[0] == "json.loads"))
        # AOI sources + settings: all hashed before load_study_area()/master_grid() and before any geopandas read or json read of study_area_meta / settings
        loads = first(lambda e: e[0] == "load_study_area")
        for n in ("study_area_wgs84.geojson", "study_area_utm44n.geojson", "study_area_meta.json", "settings.json"): self.assertLess(h(n), loads, n)
        self.assertLess(h("settings.json"), first(lambda e: e[0] == "master_grid")); self.assertLess(h("s1_preprocess.json"), loads)
        self.assertEqual(idx(lambda e: e[0] == "read_file")[0] > loads, True)
        self.assertLess(first(lambda e: e[0] == "load_study_area"), first(lambda e: e[0] == "master_grid"))
        # every Sentinel-1 product/metadata (+ rainfall csv) hashed before the first metadata parse / raster read
        s1_hash_idx = idx(lambda e: e[0] == "hash" and (e[1].startswith("S1A_IW_D092_") or e[1].endswith("antecedent_before_s1.csv")))
        run_parse = [i for i in idx(lambda e: e[0] in ("json.loads", "tif_info")) if i > s1_hash_idx[0]]                      # first metadata parse / raster read inside run()
        self.assertGreater(s1_hash_idx[0], first(lambda e: e[0] == "master_grid"))                                              # run() starts only after the preflight + AOI/grid steps
        self.assertEqual(len([i for i in s1_hash_idx if i < run_parse[0]]), 8 * 7 + 1)                                       # 48 rasters + 8 metadata + rainfall csv
        # nothing at all is parsed/read before the config hash (i.e. nothing ran at import / before preflight)
        self.assertEqual(ev[0][0], "hash")
        self.assertFalse([e for e in ev[:h("s1_preprocess.json")] if e[0] != "hash"])
        # and the same source files are re-hashed afterwards (compared after all outputs were written)
        self.assertGreater(len(idx(lambda e: e == ("hash", "study_area_wgs84.geojson"))), 1); self.assertGreater(len(idx(lambda e: e == ("hash", "settings.json"))), 1)

    def test_manifest_records_aoi_config_settings_hashes_and_source(self):
        self.assertEqual(self.instrumented_main()[0], 0)
        m = json.loads((self.root / "outputs" / "s1_2021_persistence" / "reports" / "s1_2021_persistence_manifest.json").read_text()); ps = m["preflight_sources"]
        self.assertEqual(len(ps), 5); self.assertTrue(m["input_hashes_unchanged"]); self.assertIn("file-backed", m["aoi_source"])
        for k, v in ps.items(): self.assertEqual(v["sha256"], hashlib.sha256(Path(v["path"]).read_bytes()).hexdigest(), k); self.assertEqual(m["input_sha256_before"][k], v["sha256"]); self.assertEqual(m["input_sha256_after_all_outputs"][k], v["sha256"])
        self.assertTrue(any("study_area_wgs84" in k for k in ps)); self.assertTrue(any("study_area_utm44n" in k for k in ps)); self.assertTrue(any("settings.json" in k for k in ps)); self.assertTrue(any("s1_preprocess.json" in k for k in ps))

    def test_optional_meta_absent_is_recorded_not_required(self):
        (self.proc / "study_area_meta.json").unlink(); rc, ev = self.instrumented_main(); self.assertEqual(rc, 0)
        m = json.loads((self.root / "outputs" / "s1_2021_persistence" / "reports" / "s1_2021_persistence_manifest.json").read_text()); self.assertEqual(len(m["preflight_sources"]), 4); self.assertEqual(len(m["preflight_absent_optional"]), 1)

    def test_missing_aoi_file_stops_before_anything_is_parsed_or_written(self):
        (self.proc / "study_area_utm44n.geojson").unlink(); rc, ev = self.instrumented_main(); self.assertEqual(rc, 2)
        self.assertFalse([e for e in ev if e[0] != "hash"]); self.assertFalse((self.root / "outputs" / "s1_2021_persistence").exists())

    def test_aoi_file_changing_during_run_is_detected(self):
        wgs = self.proc / "study_area_wgs84.geojson"; n = {"c": 0}
        def hook(p, digest):
            if Path(p).name == "study_area_wgs84.geojson":
                n["c"] += 1
                if n["c"] >= 2: return "tampered"                                                                             # the later (post-write) hash differs from the preflight one
            return digest
        rc, ev = self.instrumented_main(hook); self.assertEqual(rc, 3)

    def test_import_executes_no_reads(self):
        ev = []; real_loads, real_rt = json.loads, Path.read_text
        def jl(*a, **k): ev.append("json.loads"); return real_loads(*a, **k)
        def rt(self_, *a, **k): ev.append(f"read_text {self_.name}"); return real_rt(self_, *a, **k)
        with mock.patch.object(json, "loads", jl), mock.patch.object(Path, "read_text", rt): M = load_script()
        self.assertEqual(ev, []); self.assertFalse(hasattr(M, "CFG"))                                                         # no configuration is parsed at import
        src = (ROOT / "scripts" / "s1_preprocess_persistence.py").read_text(encoding="utf-8"); self.assertNotIn("CFG = json.loads", src)

CFG0 = json.loads((ROOT / 'config' / 's1_preprocess.json').read_text(encoding='utf-8'))      # parsed once, at test-module level (not by the script under test)


class TestScript(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.indir = write_inputs(self.tmp / "in"); self.out = self.tmp / "out"
        self.rain = self.tmp / "rain.csv"; pd.DataFrame([{"s1_date": d, "category": "unassigned", "prior_1d_aoi_mean_mm": float(i), "prior_30d_aoi_mean_mm": 10.0 * i + 1} for i, d in enumerate(DATES)]).to_csv(self.rain, index=False)

    def go(self, outdir=None, rain="default", indir=None, aoi=AOI, shared=()):
        return S.run(indir or self.indir, outdir or self.out, CFG0, GRID, aoi, self.rain if rain == "default" else rain, DATES, shared_dirs=shared)

    def test_full_run_expected_counts_and_outputs(self):
        h0 = tree_hash(self.indir); rc, info = self.go(); self.assertEqual(rc, 0, info); self.assertTrue(info["preserved"])
        outs = S.planned_outputs(self.out.resolve()); [self.assertTrue(p.exists(), k) for k, p in outs.items() if "rain" not in k or True]
        self.assertEqual(tree_hash(self.indir), h0)                                                                  # inputs byte-identical after the run
        cc = pd.read_csv(outs["class_counts"]); pr = cc[(cc.threshold_db == 5.0) & (cc.persistent_cut_dates == 6)].set_index("class")
        n_in = int(INSIDE.sum()); self.assertEqual(pr.loc["persistent", "cells"], 16); self.assertEqual(pr.loc["single-date", "cells"], 16); self.assertEqual(pr.loc["recurrent", "cells"], 32)   # RECUR4 (4 dates) + NOVONLY (3 dates)
        self.assertEqual(int(pr["cells"].sum()), n_in)
        cut5 = cc[(cc.threshold_db == 5.0) & (cc.persistent_cut_dates == 5)].set_index("class"); cut7 = cc[(cc.threshold_db == 5.0) & (cc.persistent_cut_dates == 7)].set_index("class")
        self.assertEqual((cut5.loc["persistent", "cells"], cut7.loc["persistent", "cells"]), (16, 16))              # sensitivity rows exist for 5/6/7
        self.assertEqual(pr.loc["persistent", "mean_bright_frequency"], 1.0)
        import rasterio
        with rasterio.open(outs["ras_valid_date_count"]) as ds: vc = ds.read(1)
        self.assertEqual(int(vc[NODATA_PATCH].max()), 6); self.assertEqual(int(vc[PERSIST].min()), 8)                # NoData dates are not counted valid, never zero-filled
        with rasterio.open(outs["ras_count_5"]) as ds: c5 = ds.read(1)
        self.assertTrue((c5[PERSIST] == 8).all()); self.assertTrue((c5[RECUR4] == 4).all()); self.assertTrue((c5[NOVONLY] == 3).all()); self.assertTrue((c5[SINGLE_] == 1).all())
        with rasterio.open(outs["ras_persistence_class_gt5_cut6"]) as ds: pc = ds.read(1); self.assertEqual(ds.nodata, 255.0)
        self.assertTrue((pc[PERSIST] == sp.PERSISTENT).all()); self.assertTrue((pc[NOVONLY] == sp.RECURRENT).all()); self.assertTrue((pc[SINGLE_] == sp.SINGLE).all())
        pdz = pd.read_csv(outs["per_date"]); self.assertEqual(len(pdz), 16); self.assertTrue((pdz.valid_share_pct > 99).all())
        dec = pd.read_csv(outs["decomp"]); r = dec[(dec.persistent_cut_dates == 6) & (dec.date_utc == "2021-11-04")].iloc[0]
        self.assertEqual((r.bright_cells, r["persistent_cells"], r["single-date_cells"], r["recurrent_cells"]), (16 * 4, 16, 16, 32))
        self.assertEqual(r.bright_not_in_other_comparison_dates_cells, 16 + 16)                                       # NOVONLY and SINGLE_ are bright here but never on the other comparison dates
        comp = pd.read_csv(outs["components"]); self.assertTrue((comp[comp["class"] == "persistent"].cells == 16).all())
        man = json.loads(outs["manifest"].read_text()); self.assertTrue(man["input_hashes_unchanged"]); self.assertFalse(man["status_json_modified"]); self.assertEqual(man["aoi_fingerprint"]["loaded_aoi"], FP)
        rep = outs["report"].read_text(encoding="utf-8"); self.assertIn("IDENTICAL", rep); self.assertIn("not a dry baseline", rep); self.assertIn("not flood classification", rep.lower().replace("**", "")); self.assertNotIn("flood extent:", rep.lower())
        self.assertIn(str(self.indir.resolve()), rep)

    def test_rainfall_join_only_verified_columns(self):
        rc, info = self.go(); outs = S.planned_outputs(self.out.resolve()); j = pd.read_csv(outs["rain_join"])
        self.assertEqual(rc, 0); self.assertTrue({"prior_1d_aoi_mean_mm", "prior_30d_aoi_mean_mm"} <= set(j.columns)); self.assertFalse([c for c in j.columns if c.startswith("prior_3d") or c.startswith("prior_7d") or c.startswith("prior_14d")])
        a = pd.read_csv(outs["rain_assoc"]); self.assertEqual(set(a.rainfall_column), {"prior_1d_aoi_mean_mm", "prior_30d_aoi_mean_mm"}); self.assertTrue((a.n_dates == 8).all())
        self.assertIn("PROVISIONAL", outs["report"].read_text(encoding="utf-8"))

    def test_rainfall_absent_or_mismatched_is_skipped_not_blocking(self):
        rc, info = self.go(outdir=self.tmp / "o2", rain=self.tmp / "nope.csv"); self.assertEqual(rc, 0); self.assertEqual(info["rain_info"]["skipped_reason"], "file not found")
        self.assertFalse(S.planned_outputs((self.tmp / "o2").resolve())["rain_join"].exists())
        pd.DataFrame([{"s1_date": "2015-01-01", "prior_1d_aoi_mean_mm": 1.0}]).to_csv(self.rain, index=False); rc, info = self.go(outdir=self.tmp / "o3"); self.assertEqual(rc, 0); self.assertIn("do not match", info["rain_info"]["skipped_reason"])
        self.assertIn("not joined", S.planned_outputs((self.tmp / "o3").resolve())["report"].read_text(encoding="utf-8")); rc, info = self.go(outdir=self.tmp / "o4", rain=None); self.assertEqual(rc, 0)

    def test_grid_mismatch_refused_before_any_output(self):
        p = self.indir / "S1A_IW_D092_20211104_VV_dB.tif"; p.unlink()
        shifted = make_master_grid(gpd.GeoSeries([box(80.1805, 13.00, 80.1905, 13.01)], crs=4326).to_crs(32644).total_bounds)
        write_raster(p, np.full(shifted.shape, -12.0, "float32"), shifted, sp.NODATA, "t", "float32")
        rc, info = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("2021-11-04 VV dB" in x and ("shape" in x or "transform" in x) for x in info["stops"]), info["stops"]); self.assertFalse(self.out.exists())

    def test_missing_input_lists_exact_path_and_substitutes_nothing(self):
        (self.indir / "S1A_IW_D092_20210917_VH_validfrac.tif").unlink(); (self.indir / "S1A_IW_D092_20211116_meta.json").unlink(); rc, info = self.go()
        self.assertEqual(rc, 2); txt = " ".join(info["stops"]); self.assertIn(str(self.indir.resolve() / "S1A_IW_D092_20210917_VH_validfrac.tif"), txt); self.assertIn("20211116_meta.json", txt); self.assertFalse(self.out.exists())

    def test_aoi_fingerprint_checks(self):
        for d in DATES[:1]: m = self.indir / f"S1A_IW_D092_{d.replace('-', '')}_meta.json"; j = json.loads(m.read_text()); j["aoi_fingerprint"] = "deadbeef0000"; m.write_text(json.dumps(j))
        rc, info = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("disagree" in x for x in info["stops"]))                     # metadata files disagree with each other
        write_inputs(self.indir, fp="deadbeef0000"); rc, info = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("loaded for this run" in x for x in info["stops"]))   # consistent but != loaded AOI
        write_inputs(self.indir, fp=FP); rc, info = self.go(aoi=box(80.18, 13.00, 80.195, 13.01)); self.assertEqual(rc, 2)                 # a different AOI geometry is refused too
        rc, info = self.go(); self.assertEqual(rc, 0, info)

    def test_non_qa_pass_metadata_refused(self):
        write_inputs(self.indir, status="EXPORTED (QA pending)"); rc, info = self.go(); self.assertEqual(rc, 2); self.assertTrue(any("not QA_PASS" in x for x in info["stops"]))

    def test_no_overwrite_existing_outputs_untouched(self):
        self.assertEqual(self.go()[0], 0); h = tree_hash(self.out); rc, info = self.go(); self.assertEqual(rc, 2); self.assertIn("existing outputs", info["stops"][0]); self.assertEqual(tree_hash(self.out), h)
        (self.tmp / "o9" / "tables").mkdir(parents=True); mine = S.planned_outputs((self.tmp / "o9").resolve())["per_date"]; mine.write_text("USER FILE"); rc, _ = self.go(outdir=self.tmp / "o9"); self.assertEqual(rc, 2); self.assertEqual(mine.read_text(), "USER FILE")

    def test_output_dir_isolation(self):
        rc, info = self.go(outdir=self.indir / "sub"); self.assertEqual(rc, 2); self.assertIn("overlaps the input", info["stops"][0])
        rc, info = self.go(outdir=self.tmp / "shared" / "x", shared=(self.tmp / "shared",)); self.assertEqual(rc, 2); self.assertIn("shared existing outputs", info["stops"][0])
        rc, info = self.go(outdir=self.tmp); self.assertEqual(rc, 2)                                                                         # an output dir that CONTAINS the inputs

    def shared(self):
        base = self.tmp / "outputs"; d = tuple(base / n for n in ("reports", "tables", "figures")); [x.mkdir(parents=True, exist_ok=True) for x in d]; return base, d

    def test_shared_dir_overlap_is_symmetric_and_writes_nothing(self):
        base, sd = self.shared(); h0 = tree_hash(base)
        cases = [base, base / "reports", base / "tables" / "x", base / "figures" / "a" / "b", self.tmp]                     # ancestor of all three, equal, nested, deeply nested, ancestor of everything
        for oc in cases:
            rc, info = self.go(outdir=oc, shared=sd); self.assertEqual(rc, 2, str(oc)); self.assertIn("overlaps the", info["stops"][0], str(oc))                  # shared-dir message, or the input-dir one for the case that also contains the inputs
        self.assertEqual(tree_hash(base), h0); self.assertEqual(h0, {})                                                      # no file written anywhere under outputs/
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), sorted(["in", "outputs", "rain.csv"]))                   # nothing else created (no out/, no stray dirs)

    def test_each_shared_dir_checked_individually(self):
        base, sd = self.shared()
        for one in sd:                                                                                                       # only ONE shared dir given: ancestor/nested/equal still refused
            for oc in (one, one / "n", one.parent):
                rc, info = self.go(outdir=oc, shared=(one,)); self.assertEqual(rc, 2, f"{one.name} {oc}")

    def test_dedicated_sibling_dir_under_outputs_is_accepted(self):
        base, sd = self.shared(); rc, info = self.go(outdir=base / "s1_2021_persistence", shared=sd); self.assertEqual(rc, 0, info)
        rc, info = self.go(outdir=base / "s1_2021_persistence_v2", shared=sd); self.assertEqual(rc, 0, info)                  # a sibling whose NAME merely starts like a shared dir is not an overlap
        (base / "reports2").mkdir(); self.assertEqual(self.go(outdir=base / "reports2" / "p", shared=sd)[0], 0)

    def test_all_inputs_hashed_before_any_content_is_parsed(self):
        from unittest import mock
        ev = []; real_hash, real_info, real_loads = sp.sha256_file, S.tif_info, json.loads
        def h(p): ev.append(("hash", Path(p).name)); return real_hash(p)
        def ti(p): ev.append(("tif_info", Path(p).name)); return real_info(p)
        def jl(*a, **k): ev.append(("json", "")); return real_loads(*a, **k)
        with mock.patch.object(sp, "sha256_file", h), mock.patch.object(S, "tif_info", ti), mock.patch.object(S.json, "loads", jl): rc, info = self.go()
        self.assertEqual(rc, 0, info); first_parse = next(i for i, e in enumerate(ev) if e[0] != "hash"); names = [e[1] for e in ev[:first_parse]]
        self.assertEqual(first_parse, 8 * 7 + 1 + 1)                                                                          # 48 rasters + 8 metadata + config + rainfall CSV, all before any parse
        self.assertIn("rain.csv", names); self.assertIn("s1_preprocess.json", names); self.assertTrue(any(n.endswith("_meta.json") for n in names)); self.assertTrue(any(n.endswith("_VV_dB.tif") for n in names))
        self.assertGreater(len([e for e in ev if e[0] == "hash"]), first_parse)                                                # and they are hashed again afterwards (after reading / after outputs)

    def test_manifest_records_library_versions(self):
        self.assertEqual(self.go()[0], 0); sw = json.loads(S.planned_outputs(self.out.resolve())["manifest"].read_text())["software"]
        for k in ("python", "numpy", "pandas", "rasterio", "geopandas", "scipy", "matplotlib"): self.assertTrue(sw.get(k), k)

    def test_reproducible_stable_output(self):
        self.assertEqual(self.go(outdir=self.tmp / "r1")[0], 0); self.assertEqual(self.go(outdir=self.tmp / "r2")[0], 0); a, b = tree_hash(self.tmp / "r1"), tree_hash(self.tmp / "r2")
        self.assertEqual(sorted(a), sorted(b))
        for k in a:
            if k.endswith("_manifest.json") or k.endswith("_report.md"): continue                                  # carry timestamps / absolute paths
            self.assertEqual(a[k], b[k], k)
        m1, m2 = [json.loads((self.tmp / d / "reports" / "s1_2021_persistence_manifest.json").read_text()) for d in ("r1", "r2")]
        for m in (m1, m2): [m.pop(k) for k in ("created_utc", "seconds", "outputs", "resolved_inputs", "rainfall")]
        self.assertEqual(m1, m2)
        r1, r2 = [(self.tmp / d / "reports" / "s1_2021_persistence_report.md").read_text(encoding="utf-8").replace(str((self.tmp / d).resolve()), "OUT") for d in ("r1", "r2")]; self.assertEqual(r1, r2)

    def test_read_only_inputs_still_work(self):
        files = [p for p in self.indir.iterdir()]
        for p in files: os.chmod(p, stat.S_IREAD)
        try: rc, info = self.go(); self.assertEqual(rc, 0, info)
        finally:
            for p in files: os.chmod(p, stat.S_IREAD | stat.S_IWRITE)

    def test_source_guards(self):
        src = (ROOT / "scripts" / "s1_preprocess_persistence.py").read_text(encoding="utf-8") + (ROOT / "src" / "flood_detection" / "s1_persistence.py").read_text(encoding="utf-8")
        for bad in ("status.record", "import ee", "np.clip", "unlink", "os.remove", "rmtree", "mode=\"w\"", "resample", "reproject", "--overwrite"): self.assertNotIn(bad, src, bad)
        self.assertIn("sha256_file", src); self.assertIn("planned_outputs", src)


if __name__ == "__main__":
    unittest.main()
