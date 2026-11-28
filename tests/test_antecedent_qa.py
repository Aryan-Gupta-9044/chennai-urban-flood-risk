"""Antecedent-rainfall QA tool tests. SYNTHETIC daily series only (no real data, no network)."""
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
spec = importlib.util.spec_from_file_location("qa_ante", ROOT / "scripts" / "qa_antecedent_rainfall.py"); Q = importlib.util.module_from_spec(spec); spec.loader.exec_module(Q)
D0 = date(2021, 8, 6); DAYS = [D0 + timedelta(days=i) for i in range(115)]; WINS = (1, 3, 7, 14, 30); S1 = ["2021-09-05", "2021-11-28"]


def daily(vals=None, bad=()):
    rows = [{"date": d.isoformat(), "status": "OK", "aoi_mean_mm": round(0.5 + (i % 7) * 0.25, 4) if vals is None else vals[i], "aoi_valid_coverage": 1.0} for i, d in enumerate(DAYS)]
    for d, st in bad:
        r = next(x for x in rows if x["date"] == d); r["status"] = st
    return pd.DataFrame(rows)


def ante_from(dl, drop=()):
    by = {r["date"]: r for _, r in dl.iterrows()}; out = []
    for s in S1:
        d0 = date.fromisoformat(s); row = {"s1_date": s}
        for n in WINS:
            ex = Q.window_dates(d0, n); ms = [d for d in ex if by[d.isoformat()]["status"] != "OK"]
            row[f"prior_{n}d_aoi_mean_mm"] = None if ms else round(sum(by[d.isoformat()]["aoi_mean_mm"] for d in ex), 2); row[f"prior_{n}d_missing_days"] = len(ms)
        out.append(row)
    return pd.DataFrame(out)


class T(unittest.TestCase):
    def test_window_convention_excludes_scene_date(self):
        w = Q.window_dates(date(2021, 9, 5), 3); self.assertEqual(w, [date(2021, 9, 2), date(2021, 9, 3), date(2021, 9, 4)]); self.assertNotIn(date(2021, 9, 5), Q.window_dates(date(2021, 9, 5), 30))
        self.assertEqual(Q.window_dates(date(2021, 9, 5), 30)[0], date(2021, 8, 6))                                   # first context day = D-30

    def test_correct_table_matches_everywhere(self):
        dl = daily(); q, pr, cand = Q.audit(ante_from(dl), dl); self.assertEqual(len(q), 10); self.assertTrue(q["result"].str.startswith("MATCH").all(), q["result"].tolist()); self.assertEqual(pr, [])
        self.assertTrue((q["expected_n"] == q["window_days"]).all()); self.assertTrue((q["missing_n"] == 0).all())

    def test_wrong_value_is_flagged_and_candidate_corrects_only_it(self):
        dl = daily(); a = ante_from(dl); a.loc[0, "prior_7d_aoi_mean_mm"] += 1.0; q, pr, cand = Q.audit(a, dl)
        bad = q[~q["result"].str.startswith("MATCH")]; self.assertEqual(len(bad), 1); self.assertIn("MISMATCH", bad.iloc[0]["result"]); self.assertEqual(bad.iloc[0]["window_days"], 7)
        self.assertAlmostEqual(cand.loc[0, "prior_7d_aoi_mean_mm"], ante_from(dl).loc[0, "prior_7d_aoi_mean_mm"], places=2); self.assertEqual(a.loc[1, "prior_7d_aoi_mean_mm"], cand.loc[1, "prior_7d_aoi_mean_mm"])

    def test_off_by_one_window_shift_is_detected(self):
        dl = daily(); a = ante_from(dl); by = {r["date"]: r["aoi_mean_mm"] for _, r in dl.iterrows()}
        a.loc[0, "prior_3d_aoi_mean_mm"] = round(sum(by[(date(2021, 9, 5) - timedelta(days=k)).isoformat()] for k in range(0, 3)), 2)     # includes D, excludes D-3 (wrong convention)
        q, pr, _ = Q.audit(a, dl); self.assertTrue(any("MISMATCH" in r for r in q[(q.s1_date == "2021-09-05") & (q.window_days == 3)]["result"]))

    def test_missing_day_is_not_zero_filled_and_blank_is_consistent(self):
        dl = daily(bad=[("2021-09-02", "MISSING")]); a = ante_from(dl); q, pr, cand = Q.audit(a, dl)
        r = q[(q.s1_date == "2021-09-05") & (q.window_days == 3)].iloc[0]; self.assertEqual(r["missing_n"], 1); self.assertIn("2021-09-02(MISSING)", r["missing_dates"]); self.assertTrue(pd.isna(r["recalculated_mean_mm"])); self.assertTrue(r["result"].startswith("CONSISTENT"))
        r1 = q[(q.s1_date == "2021-09-05") & (q.window_days == 1)].iloc[0]; self.assertEqual(r1["missing_n"], 0)                       # 1-day window (09-04) unaffected

    def test_value_reported_despite_missing_day_is_flagged(self):
        dl = daily(bad=[("2021-09-02", "MISSING")]); a = ante_from(daily()); q, pr, cand = Q.audit(a, dl)
        r = q[(q.s1_date == "2021-09-05") & (q.window_days == 3)].iloc[0]; self.assertIn("MISMATCH: reported a value although", r["result"]); self.assertTrue(pd.isna(cand.loc[0, "prior_3d_aoi_mean_mm"]))

    def test_blank_reported_but_complete_is_flagged(self):
        dl = daily(); a = ante_from(dl); a.loc[1, "prior_14d_aoi_mean_mm"] = None; q, pr, cand = Q.audit(a, dl)
        self.assertTrue(any("reported blank although" in x for x in q["result"])); self.assertFalse(pd.isna(cand.loc[1, "prior_14d_aoi_mean_mm"]))

    def test_reported_missing_count_mismatch_flagged(self):
        dl = daily(); a = ante_from(dl); a.loc[0, "prior_30d_missing_days"] = 2; q, _, _ = Q.audit(a, dl); self.assertTrue(any("reported missing_days 2 != 0" in x for x in q["result"]))

    def test_nested_window_monotonicity_check(self):
        dl = daily(); a = ante_from(dl); a.loc[0, "prior_30d_aoi_mean_mm"] = 0.1; q, pr, _ = Q.audit(a, dl); self.assertTrue(any("nested windows cannot decrease" in p for p in pr))

    def test_absent_and_duplicate_dates_and_bad_inputs(self):
        dl = daily().iloc[10:].reset_index(drop=True); q, pr, _ = Q.audit(ante_from(daily()), dl)                                         # first 10 days absent
        r = q[(q.s1_date == "2021-09-05") & (q.window_days == 30)].iloc[0]; self.assertEqual(r["missing_n"], 10); self.assertIn("2021-08-06(absent from series)", r["missing_dates"]); self.assertTrue(pd.isna(r["recalculated_mean_mm"]))   # 08-06..08-15 absent
        dd = pd.concat([daily(), daily().iloc[[3]]]); self.assertTrue(any("duplicate" in p for p in Q.audit(ante_from(daily()), dd)[1]))
        self.assertIsNotNone(Q.audit(ante_from(daily()), daily().drop(columns=["status"]))[1]); self.assertIsNone(Q.audit(ante_from(daily()), daily().drop(columns=["status"]))[0])

    def test_cli_read_only_new_dir_no_overwrite_and_candidate(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t); dl = daily(); a = ante_from(dl); a.loc[0, "prior_1d_aoi_mean_mm"] += 5; ia, idl, od = t / "ante.csv", t / "daily.csv", t / "qa"
            a.to_csv(ia, index=False); dl.to_csv(idl, index=False); h = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (ia, idl)]
            with mock.patch.object(sys, "argv", ["x", "--antecedent-csv", str(ia), "--daily-csv", str(idl), "--outdir", str(od)]), mock.patch("builtins.print"):
                self.assertEqual(Q.main(), 0); self.assertEqual(Q.main(), 2)                                                              # second run refuses to overwrite
            self.assertEqual(h, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (ia, idl)]); self.assertTrue((od / Q.NAMES["candidate"]).exists()); self.assertEqual(sorted(p.name for p in t.iterdir()), ["ante.csv", "daily.csv", "qa"])
            with mock.patch.object(sys, "argv", ["x", "--antecedent-csv", str(ia), "--daily-csv", str(idl), "--outdir", str(t)]), mock.patch("builtins.print"): self.assertEqual(Q.main(), 2)   # outdir = input folder refused

    def test_clean_table_writes_no_candidate(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t); dl = daily(); ante_from(dl).to_csv(t / "a.csv", index=False); dl.to_csv(t / "d.csv", index=False)
            with mock.patch.object(sys, "argv", ["x", "--antecedent-csv", str(t / "a.csv"), "--daily-csv", str(t / "d.csv"), "--outdir", str(t / "o")]), mock.patch("builtins.print"): self.assertEqual(Q.main(), 0)
            self.assertFalse((t / "o" / Q.NAMES["candidate"]).exists())

    def test_table_only_checks(self):
        dl = daily(); a = ante_from(dl); q, f = Q.table_checks(a); self.assertEqual(f, []); self.assertEqual(len(q), 10); self.assertTrue(q["scene_date_excluded"].all()); self.assertTrue((q["expected_n"] == q["window_days"]).all())
        self.assertTrue((q["recalculated_mean_mm"] == "NOT ASSESSED").all())
        b = a.copy(); b.loc[0, "prior_7d_aoi_mean_mm"] = 0.0; self.assertTrue(any("prior_7d" in x for x in Q.table_checks(b)[1]))
        c = a.copy(); c.loc[1, "prior_30d_aoi_mean_mm"] = c.loc[1, "prior_14d_aoi_mean_mm"] + c.loc[0, "prior_30d_aoi_mean_mm"] + 50    # scenes here are 84 days apart -> cross-scene rule not applicable
        self.assertFalse(any("exceeds the previous" in x for x in Q.table_checks(c)[1]))
        near = pd.DataFrame([{"s1_date": "2021-11-04", "prior_14d_aoi_mean_mm": 10.0, "prior_30d_aoi_mean_mm": 20.0, "prior_14d_missing_days": 0, "prior_30d_missing_days": 0},
                             {"s1_date": "2021-11-16", "prior_14d_aoi_mean_mm": 10.0, "prior_30d_aoi_mean_mm": 100.0, "prior_14d_missing_days": 0, "prior_30d_missing_days": 0}])
        self.assertTrue(any("exceeds the previous" in x for x in Q.table_checks(near)[1]))
        d = a.copy(); d.loc[0, "prior_1d_missing_days"] = 1; d.loc[1, "prior_3d_aoi_mean_mm"] = None; fs = Q.table_checks(d)[1]; self.assertTrue(any("missing days" in x for x in fs)); self.assertTrue(any("blank" in x for x in fs))

    def test_cli_table_only_needs_no_daily_file_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t); ante_from(daily()).to_csv(t / "a.csv", index=False); h = hashlib.sha256((t / "a.csv").read_bytes()).hexdigest()
            with mock.patch.object(sys, "argv", ["x", "--antecedent-csv", str(t / "a.csv"), "--daily-csv", str(t / "absent.csv"), "--outdir", str(t / "o"), "--table-only"]), mock.patch("builtins.print"): self.assertEqual(Q.main(), 0)
            self.assertEqual(h, hashlib.sha256((t / "a.csv").read_bytes()).hexdigest()); self.assertIn("NOT performed", (t / "o" / Q.NAMES["report"]).read_text())


if __name__ == "__main__": unittest.main()
