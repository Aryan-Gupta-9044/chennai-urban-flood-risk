"""Focused tests for the SUS-1 exploratory susceptibility framework (library + CLI run()). Synthetic data only; no real-data claims."""
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
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from src.flood_detection import susceptibility as su
from src.geospatial.grid import make_master_grid, write_raster

NODATA = -9999.0


def load_script():
    spec = importlib.util.spec_from_file_location("build_susceptibility_stack", ROOT / "scripts" / "build_susceptibility_stack.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class Lib(unittest.TestCase):
    def test_alignment_problems(self):
        g = make_master_grid((406000, 1463000, 406300, 1463300))
        ok = {"shape": g.shape, "crs": "EPSG:32644", "transform": tuple(g.transform)[:6], "count": 1}
        self.assertEqual(su.alignment_problems(ok, g), [])
        self.assertTrue(any("shape" in p for p in su.alignment_problems({**ok, "shape": (3, 3)}, g)))
        self.assertTrue(any("CRS" in p for p in su.alignment_problems({**ok, "crs": "EPSG:4326"}, g)))
        t = list(ok["transform"]); t[2] += 15.0       # half-pixel shift must be caught (no silent resampling)
        self.assertTrue(any("transform" in p for p in su.alignment_problems({**ok, "transform": tuple(t)}, g)))
        self.assertTrue(any("bands" in p for p in su.alignment_problems({**ok, "count": 2}, g)))

    def test_nodata_becomes_nan_not_zero(self):
        a = su.to_float_nan(np.array([1.0, NODATA, np.inf, 3.0]), NODATA)
        self.assertTrue(np.isnan(a[1]) and np.isnan(a[2]) and a[0] == 1.0)

    def test_plateau_signature(self):
        d = np.arange(1, 101, dtype=float).reshape(10, 10) + np.random.default_rng(0).random((10, 10)) * 0.01
        d = np.tile(np.linspace(1, 50, 20), (20, 1)) + np.arange(20)[:, None] * 0.37       # no equal neighbours
        d[2:8, 2:8] = 5.0                           # 36-cell plateau -> flagged
        d[12:14, 12:14] = 7.0                       # 4-cell plateau -> NOT flagged
        d[18, 18] = 0.0                             # DEM == 0 -> flagged
        ins = np.ones_like(d, bool)
        sig, nz, npl = su.plateau_signature(d, ins, 30)
        self.assertTrue(sig[2:8, 2:8].all()); self.assertFalse(sig[12:14, 12:14].any()); self.assertTrue(sig[18, 18])
        self.assertEqual(nz, 1); self.assertEqual(npl, 36)
        d2 = d.copy(); d2[2:8, 2:8] = NODATA        # NoData is never a plateau
        s2, _, _ = su.plateau_signature(d2, ins, 30)
        self.assertFalse(s2[2:8, 2:8].any())
        ins2 = ins.copy(); ins2[2:8, 2:8] = False   # outside AOI is never asserted
        s3, _, _ = su.plateau_signature(d, ins2, 30)
        self.assertFalse(s3[2:8, 2:8].any())

    def test_rank_normalisation_direction_ties_and_nan(self):
        x = np.array([[1.0, 2.0, 3.0, 4.0], [4.0, np.nan, 5.0, 100.0]])
        dom = np.ones_like(x, bool)
        hi, i1 = su.normalise(x, dom, "rank", "higher")
        lo, _ = su.normalise(x, dom, "rank", "lower")
        self.assertTrue(np.isnan(hi[1, 1]) and np.isnan(lo[1, 1]))              # NaN stays NaN, never 0
        v = np.isfinite(hi)
        self.assertTrue(((hi[v] > 0) & (hi[v] < 1)).all())
        np.testing.assert_allclose(hi[v] + lo[v], 1.0)                          # direction inverts the score
        self.assertAlmostEqual(hi[0, 3], hi[1, 0])                              # tie (4.0 and 4.0) -> equal score
        self.assertGreater(hi[1, 3], hi[1, 2])                                  # larger value -> larger score
        self.assertEqual(i1["n_ref"], 7)

    def test_robust_minmax_clip_transform_and_degenerate(self):
        x = np.concatenate([np.arange(100.0), [1e6]]).reshape(1, -1)
        s, info = su.normalise(x, np.ones_like(x, bool), "robust_minmax", "higher", None, 2, 98)
        self.assertAlmostEqual(np.nanmax(s), 1.0); self.assertAlmostEqual(np.nanmin(s), 0.0)
        self.assertEqual(s[0, -1], 1.0)                                         # outlier clipped, not dominating
        lg, _ = su.normalise(np.array([[0.0, 1.0, 10.0, 100.0, 1000.0, -5.0]]), np.ones((1, 6), bool), "rank", "higher", "log10")
        self.assertTrue(np.isnan(lg[0, 0]) and np.isnan(lg[0, 5]))              # log of <=0 is NaN, never 0
        c, info = su.normalise(np.full((3, 3), 2.0), np.ones((3, 3), bool), "rank", "higher")
        self.assertTrue(info["degenerate"] and np.isnan(c).all())
        d, _ = su.normalise(x, np.zeros_like(x, bool), "rank", "higher")        # outside the domain -> NaN
        self.assertTrue(np.isnan(d).all())

    def test_reference_population_is_the_domain_only(self):
        x = np.arange(10.0).reshape(1, 10)
        dom = np.zeros_like(x, bool); dom[0, :5] = True
        s, _ = su.normalise(x, dom, "rank", "higher")
        self.assertTrue(np.isnan(s[0, 5:]).all()); self.assertAlmostEqual(s[0, 4], 0.9)

    def test_weighted_index(self):
        a = np.array([[0.2, 0.4], [np.nan, 1.0]]); b = np.array([[0.6, 0.0], [0.5, 1.0]])
        r = su.weighted_index({"a": a, "b": b}, {"a": 1, "b": 3})
        self.assertAlmostEqual(r[0, 0], 0.25 * 0.2 + 0.75 * 0.6); self.assertTrue(np.isnan(r[1, 0]))       # NaN in an active indicator -> NaN
        r0 = su.weighted_index({"a": a, "b": b}, {"a": 0, "b": 1})
        self.assertAlmostEqual(r0[1, 0], 0.5)                                                              # zero-weight NaN does not propagate
        np.testing.assert_allclose(su.weighted_index({"a": a, "b": b}, {"a": 2, "b": 6})[0], r[0])         # weights are scale-free
        for bad in ({"a": -1, "b": 1}, {"a": 0, "b": 0}, {"a": np.nan, "b": 1}):
            with self.assertRaises(ValueError):
                su.weighted_index({"a": a, "b": b}, bad)
        with self.assertRaises(KeyError):
            su.weighted_index({"a": a}, {"a": 1, "b": 1})
        self.assertAlmostEqual(sum(su.normalise_weights({"a": 1, "b": 3}).values()), 1.0)

    def test_percentile_and_classes(self):
        idx = np.linspace(0, 1, 100).reshape(10, 10); idx[0, 0] = np.nan
        dom = np.ones((10, 10), bool)
        p = su.percentile_of(idx, dom); self.assertTrue(np.isnan(p[0, 0])); self.assertTrue(((p[np.isfinite(p)] > 0) & (p[np.isfinite(p)] < 100)).all())
        c = su.relative_classes(idx, dom, 5)
        self.assertEqual(c[0, 0], 0)                                            # not scored = 0 (distinct from class 1)
        self.assertEqual(set(np.unique(c[1:, :])) - {0}, {1, 2, 3, 4, 5})

    def test_hand_proxy_and_distance(self):
        drain = np.zeros((7, 7), bool); drain[3, :] = True
        dist, ir, ic = su.nearest_drainage(drain)
        self.assertEqual(dist[3, 2], 0.0); self.assertAlmostEqual(dist[0, 2], 3.0); self.assertEqual(ir[0, 2], 3)
        z = np.tile(np.arange(7.0)[:, None], (1, 7)) * 2.0                      # elevation rises with row
        h, nclip = su.hand_proxy(z, ir, ic, dist)
        self.assertAlmostEqual(h[6, 4], 6.0); self.assertEqual(h[0, 4], 0.0)    # below the drainage line: clipped to 0
        self.assertEqual(nclip, 21)
        n, _, _ = su.nearest_drainage(np.zeros((3, 3), bool)); self.assertTrue(np.isnan(n).all())   # no drainage -> NaN, not 0

    def test_hotspots_connectivity_and_min_size(self):
        m = np.zeros((10, 10), bool); m[1:4, 1:4] = True; m[5, 5] = True; m[6, 6] = True      # diagonal pair joins (8-neighbour)
        lab, n, dropped = su.label_hotspots(m, 4)
        self.assertEqual(n, 1); self.assertEqual(dropped, 1); self.assertEqual(int((lab > 0).sum()), 9)
        lab2, n2, _ = su.label_hotspots(m, 2)
        self.assertEqual(n2, 2)

    def test_hotspot_table_and_rank_robustness(self):
        lab = np.zeros((6, 6), "int32"); lab[0:2, 0:2] = 1; lab[4:6, 4:6] = 2
        idx = np.full((6, 6), np.nan); idx[lab == 1] = 0.9; idx[lab == 2] = 0.8
        raw = {"x": np.where(lab > 0, 5.0, np.nan)}; sc = {"x": np.where(lab > 0, 0.5, np.nan)}
        rows = su.hotspot_table(lab, idx, raw, sc, 30.0, None, {"s1": {1: 0.9, 2: 0.8}, "s2": {1: 0.5, 2: 0.7}})
        self.assertEqual([r["hotspot_id"] for r in rows], [1, 2]); self.assertEqual(rows[0]["rank_by_mean_index"], 1)
        self.assertEqual((rows[0]["rank_min_across_scenarios"], rows[0]["rank_max_across_scenarios"]), (1, 2))
        self.assertAlmostEqual(rows[0]["area_ha"], 4 * 900 / 1e4)

    def test_sensitivity_helpers_deterministic(self):
        names = ["a", "b", "c"]
        w1 = su.random_weights(names, 5, 7, 5.0); w2 = su.random_weights(names, 5, 7, 5.0); w3 = su.random_weights(names, 5, 8, 5.0)
        self.assertEqual(w1, w2); self.assertNotEqual(w1, w3)
        self.assertAlmostEqual(sum(w1[0].values()), 1.0)
        sw = su.scenario_weights({"a": 0.5, "b": 0.5, "c": 0.0}, {"drop_one": True, "explicit": {"e": {"a": 1}}})
        self.assertEqual(sw["drop_a"]["a"], 0.0); self.assertEqual(sw["e"], {"a": 1.0, "b": 0.0, "c": 0.0})
        x = np.random.default_rng(1).random(500)
        rho, jac = su.compare_to_base(x, x, np.ones(500, bool)); self.assertAlmostEqual(rho, 1.0); self.assertAlmostEqual(jac, 1.0)
        rho, jac = su.compare_to_base(x, -x, np.ones(500, bool)); self.assertAlmostEqual(rho, -1.0); self.assertEqual(jac, 0.0)

    def test_describe_counts_nodata_not_zero(self):
        a = np.array([[1.0, 2.0], [np.nan, 4.0]]); ins = np.ones((2, 2), bool)
        r = su.describe(a, ins, ins)
        self.assertEqual(r["n_nodata_inside_aoi"], 1); self.assertAlmostEqual(r["mean"], 7 / 3)


# ----------------------------------------------------------------------------------------------------------------------- CLI on a tiny synthetic project
def make_project(root, with_gap=False):
    root = Path(root)
    (root / "config").mkdir(parents=True); (root / "data/processed/rainfall_chirps_2021/chirps_2021").mkdir(parents=True)
    (root / "outputs/s1_water_candidates_review_v1/rasters").mkdir(parents=True); (root / "outputs/chirps_2021/tables").mkdir(parents=True)
    cfg = json.loads((ROOT / "config/susceptibility.json").read_text(encoding="utf-8"))
    cfg["params"].update(n_random_weight_scenarios=12, hotspot_min_cells=4, min_plateau_cells=30)
    (root / "config/susceptibility.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / "config/settings.json").write_text(json.dumps({"analysis_epsg": 32644, "grid_resolution_m": 30}), encoding="utf-8")
    aoi = gpd.GeoSeries([box(406000, 1463000, 406000 + 30 * 40, 1463000 + 30 * 40)], crs=32644)
    aoi.to_file(root / "data/processed/study_area_utm44n.geojson", driver="GeoJSON"); aoi.to_crs(4326).to_file(root / "data/processed/study_area_wgs84.geojson", driver="GeoJSON")
    (root / "data/processed/study_area_meta.json").write_text(json.dumps({"kind": "PROVISIONAL"}), encoding="utf-8")
    g = make_master_grid(aoi.total_bounds, 30, 32644)
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    dem = 20 - 0.15 * yy + 0.3 * np.sin(xx / 3.0) + 0.011 * xx * yy / 40            # varied, no equal neighbours
    dem[5:12, 5:12] = 3.0                                                             # flat 49-cell plateau (water-signature)
    cond = dem + np.where((np.sin(xx / 2) > 0.95), 0.2, 0.0)
    slope = np.abs(np.gradient(dem, axis=0)) + np.abs(np.gradient(dem, axis=1))
    twi = 8 - np.log(slope + 0.05) + 0.001 * xx
    acc = 1 + 3 * np.abs(np.sin(xx / 5)) * yy
    drain = np.zeros((h, w), "uint8"); drain[20, :] = 1
    if with_gap:
        slope[25, 25] = NODATA
    d = root / "data/processed"
    for n, a in (("dem_elevation", dem), ("dem_conditioned", cond), ("slope_deg", slope), ("twi", twi), ("flow_accumulation", acc)):
        write_raster(d / f"{n}_utm44n_30m.tif", a.astype("float32"), g, NODATA, n, "float32")
    write_raster(d / "drainage_network_utm44n_30m.tif", drain, g, 255, "drain", "uint8")
    s1 = root / "outputs/s1_water_candidates_review_v1/rasters"
    for n, a in (("n_dark_dates", np.zeros((h, w), "uint8")), ("n_valid_dates", np.full((h, w), 8, "uint8")), ("persistent_dark_mask", np.zeros((h, w), "uint8")),
                 ("transient_candidate_date_count", np.zeros((h, w), "uint8"))):
        write_raster(s1 / f"s1_water_candidates_{n}.tif", a, g, 255, n, "uint8")
    # native CHIRPS-like raster (0.05 deg, EPSG:4326) covering the AOI
    ll = aoi.to_crs(4326).total_bounds
    t = from_origin(ll[0] - 0.05, ll[3] + 0.05, 0.05, 0.05)
    with rasterio.open(d / "rainfall_chirps_2021/chirps_2021/2021_sep_nov_event_total_mm_native.tif", "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
                       crs="EPSG:4326", transform=t, nodata=NODATA) as dst:
        dst.write(np.full((4, 4), 1000.0, "float32"), 1)
    pd.DataFrame({"s1_date": ["2021-09-05"], "prior_7d_aoi_mean_mm": [3.0]}).to_csv(root / "outputs/chirps_2021/tables/rainfall_chirps_2021_2021_sep_nov_antecedent_before_s1.csv", index=False)
    return root


class Cli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = load_script()

    def run_once(self, root, out="outputs/susceptibility_t", **kw):
        return self.S.run(root, "config/susceptibility.json", out, **kw)

    def test_full_run_outputs_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td) / "p")
            self.assertEqual(self.run_once(root, "outputs/susceptibility_a"), 0)
            self.assertEqual(self.run_once(root, "outputs/susceptibility_b"), 0)
            a, b = root / "outputs/susceptibility_a", root / "outputs/susceptibility_b"
            for rel in ("rasters/susceptibility_index.tif", "rasters/feature_stack_raw.tif", "rasters/feature_stack_scores.tif", "rasters/domain_class.tif", "tables/hotspot_ranking.csv",
                        "tables/sensitivity_scenarios.csv", "tables/layer_statistics_and_coverage.csv", "vectors/susceptibility_hotspots_exploratory.gpkg"):
                self.assertTrue((a / rel).is_file(), rel)
            for rel in ("rasters/susceptibility_index.tif", "rasters/feature_stack_raw.tif", "tables/hotspot_ranking.csv", "tables/sensitivity_scenarios.csv", "rasters/hotspot_label.tif"):
                self.assertEqual(hashlib.sha256((a / rel).read_bytes()).hexdigest(), hashlib.sha256((b / rel).read_bytes()).hexdigest(), f"not reproducible: {rel}")
            man = json.loads((a / "reports/susceptibility_manifest.json").read_text())
            self.assertIn("EXPLORATORY", man["label"]); self.assertEqual(man["inputs_changed_during_run"], [])
            self.assertTrue(all(len(v["sha256"]) == 64 for v in man["inputs"].values())); self.assertIn("rasters/susceptibility_index.tif", man["output_sha256"])
            self.assertEqual(man["grid"]["crs"], "EPSG:32644")
            # rasters share one grid
            with rasterio.open(a / "rasters/susceptibility_index.tif") as i1, rasterio.open(a / "rasters/feature_stack_raw.tif") as i2, rasterio.open(a / "rasters/domain_class.tif") as i3:
                self.assertEqual((i1.shape, tuple(i1.transform)), (i2.shape, tuple(i2.transform))); self.assertEqual(i1.shape, i3.shape)
                idx = i1.read(1); dom = i3.read(1)
            # index defined only on scored cells, within 0..1; water signature NOT scored
            scored = dom == 1
            self.assertTrue(((idx[scored] >= 0) & (idx[scored] <= 1)).all()); self.assertTrue((idx[~scored] == NODATA).all())
            self.assertGreater((dom == 2).sum(), 0)
            h = pd.read_csv(a / "tables/hotspot_ranking.csv"); self.assertIn("EXPLORATORY", h.status.iloc[0])
            gdf = gpd.read_file(a / "vectors/susceptibility_hotspots_exploratory.gpkg"); self.assertEqual(len(gdf), len(h))

    def test_nodata_inside_aoi_is_excluded_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td) / "p", with_gap=True)
            self.assertEqual(self.run_once(root, "outputs/susceptibility_g"), 0)
            with rasterio.open(root / "outputs/susceptibility_g/rasters/domain_class.tif") as d, rasterio.open(root / "outputs/susceptibility_g/rasters/susceptibility_index.tif") as i:
                dom, idx = d.read(1), i.read(1)
            self.assertEqual(dom[25, 25], su.DOM_MISSING); self.assertEqual(idx[25, 25], NODATA)

    def test_stack_only_writes_no_index(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td) / "p")
            self.assertEqual(self.run_once(root, "outputs/susceptibility_s", stack_only=True), 0)
            o = root / "outputs/susceptibility_s"
            self.assertTrue((o / "rasters/feature_stack_raw.tif").is_file()); self.assertFalse((o / "rasters/susceptibility_index.tif").exists())

    def test_safeguards_no_overwrite_protected_and_misaligned(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td) / "p")
            self.assertEqual(self.run_once(root, "outputs/susceptibility_x"), 0)
            self.assertEqual(self.run_once(root, "outputs/susceptibility_x"), 2)                          # never overwrite
            self.assertEqual(self.run_once(root, "outputs/s1_water_candidates_review_v1/susceptibility_y"), 2)   # inside a protected dir
            self.assertEqual(self.run_once(root, "outputs/other_name"), 2)                                  # must be a susceptibility_ dir
            before = sorted(p.name for p in (root / "outputs").iterdir())
            # shift a context raster by half a pixel -> stop before writing
            p = root / "outputs/s1_water_candidates_review_v1/rasters/s1_water_candidates_n_valid_dates.tif"
            with rasterio.open(p) as s:
                arr = s.read(1); prof = s.profile
            prof["transform"] = rasterio.Affine(30, 0, prof["transform"].c + 15, 0, -30, prof["transform"].f)
            with rasterio.open(p, "w", **prof) as d:
                d.write(arr, 1)
            self.assertEqual(self.run_once(root, "outputs/susceptibility_z"), 2)
            self.assertFalse((root / "outputs/susceptibility_z/rasters").exists())
            self.assertEqual(before, sorted(p.name for p in (root / "outputs").iterdir()))

    def test_input_files_unchanged_by_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td) / "p")
            files = [p for p in root.rglob("*") if p.is_file()]
            h0 = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            self.assertEqual(self.run_once(root, "outputs/susceptibility_u"), 0)
            for p, h in h0.items():
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), h, str(p))
            self.assertFalse((root / "outputs/reports/status.json").exists())


class Wording(unittest.TestCase):
    def test_no_overclaiming_in_docs_or_script(self):
        txt = (ROOT / "scripts/build_susceptibility_stack.py").read_text(encoding="utf-8") + (ROOT / "config/susceptibility.json").read_text(encoding="utf-8")
        for must in ("EXPLORATORY", "not independently validated", "not flood risk"):
            self.assertIn(must, txt)
        cfg = json.loads((ROOT / "config/susceptibility.json").read_text(encoding="utf-8"))
        self.assertTrue(all("s1wc1" not in k and "chirps" not in k for k in cfg["indicators"]))        # S1WC-1 / CHIRPS never enter the index


if __name__ == "__main__":
    unittest.main()
