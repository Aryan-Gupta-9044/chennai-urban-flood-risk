"""M4-A: Sentinel-1 inventory expansion helpers on SYNTHETIC rows. The live Earth Engine inventory is UNTESTED until the user runs it."""
import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.flood_detection import s1_inventory as inv


def r(i, d, ps="DESCENDING", ro=92, pf="SENTINEL-1A", pols=("VV", "VH"), cov=100.0, val=99.0):
    return {"id": i, "date_utc": f"{d}T00:31:00+00:00", "pass": ps, "rel_orbit": ro, "platform": pf, "coverage_pct": cov, "valid_pct": val, **inv.pol_flags(list(pols))}


class T(unittest.TestCase):
    def test_pol_flags(self):
        self.assertEqual(inv.pol_flags(["VV", "VH"]), {"has_VV": True, "has_VH": True, "dual_pol_VV_VH": True})
        self.assertEqual(inv.pol_flags("['VV']"), {"has_VV": True, "has_VH": False, "dual_pol_VV_VH": False})
        self.assertEqual(inv.pol_flags(["HH", "HV"]), {"has_VV": False, "has_VH": False, "dual_pol_VV_VH": False})
        self.assertFalse(inv.pol_flags(None)["has_VV"])

    def test_footprint_rounding(self):
        s = inv.round_geojson({"type": "Polygon", "coordinates": [[[80.123456789, 13.1], [80.2, 13.1], [80.2, 13.2], [80.123456789, 13.1]]]})
        self.assertEqual(json.loads(s)["coordinates"][0][0], [80.12346, 13.1]); self.assertEqual(inv.round_geojson(None), "")

    def test_geometry_summary_keeps_incomplete_scenes(self):
        rows = [r("a", "2021-10-01"), r("b", "2021-10-13", cov=60.0), r("c", "2021-11-16", ps="ASCENDING", ro=33, pf="SENTINEL-1B", pols=("VV",))]
        g = {(x["pass"], x["rel_orbit"], x["platform"]): x for x in inv.geometry_summary(rows)}
        d = g[("DESCENDING", 92, "SENTINEL-1A")]
        self.assertEqual(d["n_scenes"], 2); self.assertEqual(d["n_incomplete_aoi_coverage"], 1); self.assertEqual(d["min_coverage_pct"], 60.0)   # not discarded
        self.assertEqual(d["first_date"], "2021-10-01"); self.assertEqual(d["last_date"], "2021-10-13")
        b = g[("ASCENDING", 33, "SENTINEL-1B")]; self.assertEqual((b["n_with_VV"], b["n_with_VH"], b["n_dual_pol"]), (1, 0, 0))
        self.assertEqual(sum(x["n_scenes"] for x in g.values()), 3)

    def test_assess_without_reference_does_not_assume_geometry(self):
        ok = {"mode": "IW", "pols": ["VV", "VH"], "coverage_pct": 99.0, "valid_pct": 95.0}
        v, why = inv.assess_without_reference(ok); self.assertEqual(why, []); self.assertIn("no reference geometry assumed", v)
        v, why = inv.assess_without_reference(dict(ok, coverage_pct=40.0)); self.assertIn("retained", v); self.assertTrue(why)
        v, why = inv.assess_without_reference(dict(ok, coverage_pct=None, valid_pct=None, pols=["HH"])); self.assertEqual(len(why), 3)

    def test_event_config_and_no_assumed_2021_dates(self):
        c = json.loads((ROOT / "config" / "s1_inventory_events.json").read_text())["events"]
        self.assertEqual((c["2015_dec"]["start"], c["2015_dec"]["end"]), ("2014-10-01", "2015-12-21"))
        e = c["2021_nov"]; self.assertIsNone(e["reference_geometry"]); self.assertFalse(e["uses_candidate_roles"])
        self.assertEqual(len(inv.month_windows(e["start"], e["end"])), 3)
        self.assertIn("UNVERIFIED", e["claimed_dates"][0]["claim"])

    def test_script_guards(self):
        s = (ROOT / "scripts" / "s1_inventory.py").read_text(encoding="utf-8")
        self.assertIn("--overwrite", s); self.assertIn("not overwritten", s)               # existing outputs are never silently replaced
        self.assertIn("s1_inventory_{a.event}_", s)                                         # event runs get their own file names
        self.assertIn("no flood processing", s.lower()); self.assertNotIn("PASS", s.split("def main")[0])


class TestReviewCorrections(unittest.TestCase):
    """M4-A review: (1) scenes without VV kept, (2) platform never mixed in date mosaics, (3) cache tied to AOI/query config. SYNTHETIC."""
    def setUp(self):
        import tempfile
        from shapely.geometry import box
        self.box = box; self.tmp = Path(tempfile.mkdtemp())

    def test_fingerprint_changes_with_aoi_and_query_settings(self):
        a = self.box(80.1, 12.8, 80.3, 13.2); fp, cfg = inv.query_fingerprint(a)
        self.assertEqual(fp, inv.query_fingerprint(self.box(80.1, 12.8, 80.3, 13.2))[0])                         # deterministic
        self.assertNotEqual(fp, inv.query_fingerprint(self.box(80.1, 12.8, 80.3, 13.2001))[0])                   # geometry changed
        self.assertNotEqual(fp, inv.query_fingerprint(a, dict(cfg, valid_scale_m=10))[0])                        # scale changed
        self.assertNotEqual(fp, inv.query_fingerprint(a, dict(cfg, instrumentMode="EW"))[0])                     # query filter changed
        self.assertNotEqual(fp, inv.query_fingerprint(a, dict(cfg, platform_filter="A"))[0])

    def test_cache_reused_only_when_fingerprint_and_window_match(self):
        a = self.box(80.1, 12.8, 80.3, 13.2); fp, cfg = inv.query_fingerprint(a); f = self.tmp / "w.json"
        items = [{"id": "x", "footprint": "{}"}]; win = ("2021-09-01", "2021-10-01")
        inv.cache_save(f, fp, cfg, win, items)
        self.assertEqual(inv.cache_load(f, fp, win), items)
        fp2, _ = inv.query_fingerprint(self.box(80.1, 12.8, 80.3, 13.3))
        self.assertIsNone(inv.cache_load(f, fp2, win))                                                            # AOI changed -> not reused
        self.assertIsNone(inv.cache_load(f, fp, ("2021-10-01", "2021-11-01")))                                    # window mismatch
        f.write_text("[{\"id\": \"x\", \"footprint\": \"\"}]"); self.assertIsNone(inv.cache_load(f, fp, win))  # legacy bare-list cache ignored
        f.write_text("not json"); self.assertIsNone(inv.cache_load(f, fp, win))
        inv.cache_save(f, fp, cfg, win, [{"id": "y"}]); self.assertIsNone(inv.cache_load(f, fp, win))            # no footprint -> re-query

    def test_group_mosaic_filter_includes_platform(self):
        a = inv.group_query_props("2021-11-16", "ASCENDING", 33, "SENTINEL-1A"); b = inv.group_query_props("2021-11-16", "ASCENDING", 33, "SENTINEL-1B")
        self.assertEqual((a["platform_number"], b["platform_number"]), ("A", "B")); self.assertNotEqual(a, b)
        self.assertEqual(a["orbitProperties_pass"], "ASCENDING"); self.assertEqual(a["relativeOrbitNumber_start"], 33)

    def test_script_does_not_select_vv_unconditionally_and_uses_filters(self):
        s = (ROOT / "scripts" / "s1_inventory.py").read_text(encoding="utf-8")
        stats = s[s.index("def stats(img):"):s.index("col = ee.ImageCollection")]
        self.assertNotIn('img.select("VV")', stats); self.assertIn("bn.contains(b)", stats); self.assertIn("ee.Algorithms.If", stats)   # band presence checked server-side
        self.assertIn("group_query_props", s); self.assertIn('listContains("transmitterReceiverPolarisation", "VV")', s)
        self.assertIn("query_fingerprint", s); self.assertIn("cache_load", s); self.assertNotIn("json.loads(cf.read_text", s)
        self.assertLess(s.index('valid_pct=it.get("valid_vv_pct")'), s.index("assess_without_reference(it)"))     # validity set before classification

    def test_no_vv_scene_is_retained_with_reasons(self):
        v, why = inv.assess_without_reference({"mode": "IW", "pols": ["HH", "HV"], "coverage_pct": 99.0, "valid_pct": None})
        self.assertIn("no VV", why); self.assertIn("retained", v)
        g = inv.geometry_summary([r("n", "2021-10-01", pols=("HH", "HV"), val=None)])[0]
        self.assertEqual((g["n_scenes"], g["n_with_VV"]), (1, 0))


if __name__ == "__main__": unittest.main()
