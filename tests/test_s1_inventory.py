"""V2.3 inventory / reference-readiness logic on SYNTHETIC rows (the live Earth Engine inventory is untested until run)."""
import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.flood_detection import s1_inventory as inv, ref_readiness as rr

REF = {"platform": "SENTINEL-1A", "pass": "DESCENDING", "rel_orbit": 92}
def row(i, d, ro=92, ps="DESCENDING", pf="SENTINEL-1A", verdict="COMPATIBLE"):
    return {"id": i, "date_utc": f"{d}T00:31:00+00:00", "rel_orbit": ro, "pass": ps, "platform": pf, "verdict": verdict}

class T(unittest.TestCase):
    def test_month_windows(self):
        w = inv.month_windows("2014-10-01", "2015-12-21")
        self.assertEqual(w[0], ("2014-10-01", "2014-11-01")); self.assertEqual(w[-1], ("2015-12-01", "2015-12-21")); self.assertEqual(len(w), 15)
        self.assertEqual(inv.month_windows("2015-11-20", "2015-12-21"), [("2015-11-20", "2015-12-01"), ("2015-12-01", "2015-12-21")])
        for (a, b), (c, d) in zip(w, w[1:]): self.assertEqual(b, c)
    def test_ist(self):
        u, i = inv.utc_ist(1449361860000)   # 2015-12-06T00:31:00Z
        self.assertTrue(u.startswith("2015-12-06T00:31:00")); self.assertTrue(i.startswith("2015-12-06T06:01:00") and i.endswith("+05:30"))
    def test_dedupe_and_slices(self):
        rs = [row("a", "2015-12-06"), row("a", "2015-12-06"), row("b", "2015-12-06")]
        self.assertEqual(len(inv.dedupe(rs)), 2)
        self.assertEqual(list(inv.slice_groups(inv.dedupe(rs)).values()), [["a", "b"]])
    def test_candidates(self):
        rows = [row("x", "2015-12-06"), row("y", "2015-11-24", ro=19, ps="ASCENDING", verdict="DIFFERENT GEOMETRY")]
        t = inv.candidate_table([{"date": "2015-12-06"}, {"date": "2015-11-24"}, {"date": "2015-08-20"}], rows, REF)
        self.assertEqual(t[0]["result"], "FOUND COMPATIBLE"); self.assertEqual(t[1]["result"], "FOUND ONLY WITH OTHER GEOMETRY")
        self.assertTrue(t[2]["result"].startswith("NOT FOUND"))
    def test_compat_by_month(self):
        self.assertEqual(inv.compatible_by_month([row("a", "2015-11-12"), row("b", "2015-11-24"), row("c", "2015-12-06")]),
                         {"2015-11": ["2015-11-12", "2015-11-24"], "2015-12": ["2015-12-06"]})
    def test_roles_config(self):
        c = json.loads((ROOT / "config" / "s1_candidate_roles.json").read_text())
        d = {x["date"]: x for x in c["candidates"]}
        self.assertEqual(len(d), 8); self.assertEqual(d["2015-11-12"]["category"], "known-flood"); self.assertEqual(d["2015-12-06"]["category"], "post-peak")
        self.assertNotIn("dry", d["2015-11-24"]["role"].lower().replace("not automatically", ""))
        self.assertNotIn("peak flood", d["2015-12-06"]["role"].lower().replace("not peak", ""))
    def test_reference_status(self):
        c = json.loads((ROOT / "config" / "reference_datasets.json").read_text())
        s = {d["id"]: rr.status_of(d) for d in c["datasets"]}
        self.assertTrue(s["unosat_iwmi_nov"].startswith("NOT SUITABLE FOR QUANTITATIVE"))
        self.assertTrue(all(d["access"] == "NOT YET OBTAINED" for d in c["datasets"]))
        self.assertTrue(s["alos2_20151203"].startswith("NOT YET OBTAINED"))
    def test_ingest_checks(self):
        self.assertTrue(len(rr.check_ingest({"kind": "pdf"})) >= 5)
        ok = {"kind": "raster", "crs": "EPSG:4326", "obs_date": "2015-12-03", "classes_documented": True, "extent_covers_aoi": True, "method_documented": True, "licence_ok": True}
        self.assertEqual(rr.check_ingest(ok), [])
        self.assertIn("licence not confirmed", rr.check_ingest(dict(ok, licence_ok=None)))
if __name__ == "__main__": unittest.main()
