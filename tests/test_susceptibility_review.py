"""Focused tests for the SUS-1 methodology-review module/script (experimental). Synthetic data only; no validation claims."""
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
import rasterio
from src.flood_detection import susceptibility_review as rv
from tests.test_susceptibility import make_project, load_script as load_sus1


def load_review():
    spec = importlib.util.spec_from_file_location("susceptibility_review", ROOT / "scripts" / "susceptibility_review.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class Lib(unittest.TestCase):
    def test_group_weights(self):
        w = rv.group_weights({"g1": ["a", "b", "c"], "g2": ["d"]})
        self.assertAlmostEqual(sum(w.values()), 1.0); self.assertAlmostEqual(w["a"], 1 / 6); self.assertAlmostEqual(w["d"], 0.5)
        w2 = rv.group_weights({"g1": ["a", "b"], "g2": ["c"]}, {"g1": 3, "g2": 1}); self.assertAlmostEqual(w2["a"], 0.375); self.assertAlmostEqual(w2["c"], 0.25)
        with self.assertRaises(ValueError):
            rv.group_weights({"g1": ["a"], "g2": ["a"]})

    def test_vif_effective_n_independent_and_redundant(self):
        rng = np.random.default_rng(0)
        x = {k: rng.random(4000) for k in "abc"}
        _, R = rv.spearman_matrix(x)
        np.testing.assert_allclose(rv.vif_from_corr(R), 1.0, atol=0.05); self.assertGreater(rv.effective_n(R), 2.9)
        x["d"] = x["a"] + 0.01 * rng.random(4000)                                # near-duplicate of a
        _, R2 = rv.spearman_matrix(x); v = rv.vif_from_corr(R2)
        self.assertGreater(v[0], 50); self.assertGreater(v[3], 50); self.assertLess(rv.effective_n(R2), 3.3)

    def test_rank_r2_detects_functional_dependence(self):
        rng = np.random.default_rng(1)
        a, b = rng.random(3000), rng.random(3000)
        self.assertGreater(rv.rank_r2(a - b, [a, b]) , 0.8)                       # monotone-ish combination is explained by its parts
        self.assertLess(rv.rank_r2(rng.random(3000), [a, b]), 0.02)

    def test_contribution_shares_sum_to_one_and_zero_weight(self):
        rng = np.random.default_rng(2)
        S = {"a": rng.random(2000), "b": rng.random(2000), "c": rng.random(2000)}
        rows = rv.contribution_shares(S, {"a": 0.5, "b": 0.5, "c": 0.0})
        self.assertAlmostEqual(sum(r["variance_share_of_index"] for r in rows), 1.0, places=6)
        c = [r for r in rows if r["indicator"] == "c"][0]; self.assertEqual(c["variance_share_of_index"], 0.0); self.assertTrue(np.isnan(c["spearman_with_index"]))
        S["d"] = S["a"].copy()                                                    # duplicating an indicator raises its combined share (double counting)
        s1 = sum(r["variance_share_of_index"] for r in rv.contribution_shares({"a": S["a"], "b": S["b"]}, {"a": .5, "b": .5}) if r["indicator"] == "a")
        s2 = sum(r["variance_share_of_index"] for r in rv.contribution_shares({"a": S["a"], "b": S["b"], "d": S["d"]}, {"a": 1 / 3, "b": 1 / 3, "d": 1 / 3}) if r["indicator"] in ("a", "d"))
        self.assertGreater(s2, s1 + 0.1)

    def test_merge_close_never_enters_excluded_cells(self):
        m = np.zeros((9, 9), bool); m[3:6, 2] = True; m[3:6, 4] = True               # two bars with a 1-cell gap
        dom = np.ones((9, 9), bool)
        out = rv.merge_close(m, dom, 1); self.assertTrue(out[4, 3])                  # gap closed
        dom2 = dom.copy(); dom2[:, 3] = False                                        # gap column is excluded/not scored
        out2 = rv.merge_close(m, dom2, 1); self.assertFalse(out2[:, 3].any())        # never absorbed
        np.testing.assert_array_equal(rv.merge_close(m, dom, 0), m)

    def test_excess_mean_and_ranks(self):
        v = np.array([0.9, 0.8, 0.5, 0.95, 0.4]); lab = np.array([1, 1, 0, 2, 0])
        ex = rv.excess_mass_by_label(v, lab, 0.7, 2, 2.0)
        self.assertAlmostEqual(ex[0], (0.2 + 0.1) * 2.0); self.assertAlmostEqual(ex[1], 0.25 * 2.0)
        np.testing.assert_allclose(rv.mean_by_label(v, lab, 2), [0.85, 0.95])
        np.testing.assert_array_equal(rv.ranks_desc(np.array([0.1, 0.5, 0.5, 0.9])), [4, 2, 3, 1])      # ties by position, deterministic

    def test_stability_summary(self):
        base = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        M = np.tile(base, (6, 1)); st = rv.stability_summary(M, base, 2)
        self.assertEqual(st["top_k_retention"], 1.0); self.assertEqual(st["median_rank_range_topk"], 0.0)
        M2 = np.vstack([base, base[::-1]]); st2 = rv.stability_summary(M2, base, 2)
        self.assertEqual(st2["top_k_retention"], 0.5); self.assertEqual(int(st2["rank_max"][0] - st2["rank_min"][0]), 4)

    def test_shape_metrics_compact_vs_ragged(self):
        lab = np.zeros((12, 12), int); lab[1:5, 1:5] = 1; lab[7, 1:11] = 2             # 4x4 square vs 1x10 line
        m = rv.shape_metrics(lab, 30.0)
        self.assertGreater(m[1]["compactness"], m[2]["compactness"]); self.assertAlmostEqual(m[1]["perimeter_m"], 16 * 30.0); self.assertEqual(m[1]["bbox_fill_ratio"], 1.0)

    def test_agreement_class(self):
        a = np.array([[1, 1, 0, 0]], bool); b = np.array([[1, 0, 1, 0]], bool); d = np.array([[1, 1, 1, 0]], bool)
        np.testing.assert_array_equal(rv.agreement_class(a, b, d), [[3, 1, 2, 255]])     # 255 = not scored, never 'neither'


class Cli(unittest.TestCase):
    def test_review_runs_is_read_only_and_audits_pass(self):
        S1, RV = load_sus1(), load_review()
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td) / "p")
            self.assertEqual(S1.run(root, "config/susceptibility.json", "outputs/susceptibility_v1"), 0)
            cfg = json.loads((ROOT / "config/susceptibility_review.json").read_text())
            cfg["hotspot"].update(min_cells_sensitivity=[4, 8], merged_min_cells=4, block_cells_sensitivity=[5], block_cells_primary=5, merge_closing_iterations=[1])
            (root / "config/susceptibility_review.json").write_text(json.dumps(cfg))
            files = [p for p in root.rglob("*") if p.is_file()]
            h0 = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            self.assertEqual(RV.run(root, "config/susceptibility_review.json", "outputs/susceptibility_review_t"), 0)
            for p, h in h0.items():                                                     # SUS-1 outputs and every input unchanged
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), h, str(p))
            o = root / "outputs/susceptibility_review_t"
            au = pd.read_csv(o / "tables/t3_audit_checks.csv"); self.assertTrue((au.result == "PASS").all(), au[au.result != "PASS"].to_string())
            for rel in ("tables/t1_scheme_distribution_and_overlap.csv", "tables/t2_ranking_stability_summary.csv", "tables/t4_hand_variants.csv", "figures/susceptibility_review_summary.png",
                        "reports/susceptibility_review_manifest.json", "rasters/index_C_reduced_no_twi.tif"):
                self.assertTrue((o / rel).is_file(), rel)
            man = json.loads((o / "reports/susceptibility_review_manifest.json").read_text())
            self.assertEqual(man["inputs_or_sus1_changed_during_run"], []); self.assertIn("EXPERIMENTAL", man["label"])

    def test_safeguards(self):
        S1, RV = load_sus1(), load_review()
        with tempfile.TemporaryDirectory() as td:
            root = make_project(Path(td) / "p")
            self.assertEqual(S1.run(root, "config/susceptibility.json", "outputs/susceptibility_v1"), 0)
            (root / "config/susceptibility_review.json").write_text((ROOT / "config/susceptibility_review.json").read_text())
            self.assertEqual(RV.run(root, "config/susceptibility_review.json", "outputs/susceptibility_v1/susceptibility_review_x"), 2)   # inside SUS-1 baseline
            self.assertEqual(RV.run(root, "config/susceptibility_review.json", "outputs/other"), 2)
            (root / "outputs/susceptibility_review_e").mkdir(); (root / "outputs/susceptibility_review_e/keep.txt").write_text("x")
            self.assertEqual(RV.run(root, "config/susceptibility_review.json", "outputs/susceptibility_review_e"), 2)                  # never overwrite
            self.assertEqual((root / "outputs/susceptibility_review_e/keep.txt").read_text(), "x")


if __name__ == "__main__":
    unittest.main()
