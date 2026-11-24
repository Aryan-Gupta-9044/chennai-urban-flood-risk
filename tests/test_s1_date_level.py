"""M4B: date-level multi-slice coverage logic. SYNTHETIC geometries only - these tests say nothing about the real Chennai 2021 scenes."""
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import box, mapping
from src.flood_detection import s1_date_level as dl, s1_inventory as inv

AOI = box(80.10, 12.85, 80.30, 13.20)


def fpj(y0, y1): return json.dumps(mapping(box(80.0, y0, 80.5, y1)))


def row(i, y0, y1, d="2021-11-16", t=0, ps="DESCENDING", ro=92, pf="SENTINEL-1A", pols="['VV', 'VH']", **kw):
    return {"id": i, "date_utc": f"{d}T00:31:00+00:00", "pass": ps, "rel_orbit": ro, "platform": pf, "pols": pols, "t": t, "abs_orbit": 40000, "footprint": fpj(y0, y1), **kw}


def met(rows): return dl.footprint_metrics(AOI, [dl.footprint_geom(r["footprint"]) for r in rows])


class TestTwoSliceMosaic(unittest.TestCase):
    def test_adjacent_slices_cover_aoi_once(self):
        rows = [row("n", 13.00, 13.40), row("s", 12.60, 13.00, t=25000)]        # shared edge at 13.00
        m = met(rows)
        self.assertGreaterEqual(m["combined_footprint_pct"], 99.999); self.assertEqual(m["gap_pct_of_aoi"], 0.0)
        self.assertLess(m["overlap_pct_of_aoi"], 1e-6)
        self.assertAlmostEqual(m["slice_coverage_pct"][0] + m["slice_coverage_pct"][1], m["combined_footprint_pct"], places=2)
        self.assertGreater(m["slice_coverage_pct"][0], 0); self.assertLess(m["slice_coverage_pct"][0], 100)

    def test_overlap_is_not_counted_twice(self):
        rows = [row("n", 12.98, 13.40), row("s", 12.60, 13.02, t=25000)]        # 0.04 deg overlap strip
        m = met(rows)
        self.assertAlmostEqual(m["combined_footprint_pct"], 100.0, places=3)
        self.assertGreater(m["overlap_pct_of_aoi"], 0)
        self.assertAlmostEqual(m["sum_of_slices_pct"] - m["overlap_pct_of_aoi"], m["combined_footprint_pct"], places=2)   # sum - overlap = union
        self.assertGreater(m["sum_of_slices_pct"], 100.0)                                                                  # naive sum would exceed 100 %
        self.assertLessEqual(m["combined_footprint_pct"], 100.0 + 1e-9)

    def test_missing_footprint_gives_no_combined_value(self):
        self.assertIsNone(dl.footprint_metrics(AOI, [dl.footprint_geom(fpj(13.0, 13.4)), dl.footprint_geom(None)]))
        v, why = dl.assess_date(2, None, {"vv": 99.0, "vh": 99.0}, {}); self.assertTrue(v.startswith("NOT ASSESSED"))


class TestIncompleteCombinedCoverage(unittest.TestCase):
    def test_gap_between_slices_is_reported_and_not_complete(self):
        rows = [row("n", 13.06, 13.40), row("s", 12.60, 12.96, t=25000)]        # 0.10 deg gap
        m = met(rows); self.assertGreater(m["gap_pct_of_aoi"], 20.0); self.assertGreater(m["gap_km2"], 100.0)
        self.assertAlmostEqual(m["combined_footprint_pct"] + m["gap_pct_of_aoi"], 100.0, places=2)
        v, why = dl.assess_date(2, m, {"vv": 100.0, "vh": 100.0}, dl.compat_checks(rows))
        self.assertFalse(v.startswith("COMPLETE")); self.assertTrue(any("gap" in w for w in why))

    def test_complete_requires_footprint_and_both_valid_shares(self):
        rows = [row("n", 13.00, 13.40), row("s", 12.60, 13.00, t=25000)]; m = met(rows); c = dl.compat_checks(rows)
        self.assertTrue(dl.assess_date(2, m, {"vv": 99.0, "vh": 98.0}, c)[0].startswith("COMPLETE"))
        self.assertIn("PARTIAL", dl.assess_date(2, m, {"vv": 99.0, "vh": 80.0}, c)[0])                       # low VH validity
        v, why = dl.assess_date(2, m, {"vv": None, "vh": None}, c)                                         # not measured is never 'complete'
        self.assertTrue(v.startswith("FOOTPRINT COMPLETE; PIXEL VALIDITY NOT MEASURED")); self.assertFalse(v.startswith("COMPLETE"))
        v, why = dl.assess_date(2, met([row("n", 13.06, 13.40), row("s", 12.60, 12.96)]), {"vv": 100.0, "vh": 100.0}, c)
        self.assertTrue(any("exceeds the footprint" in w for w in why))                                     # impossible pixel > footprint is flagged

    def test_no_zero_fill_of_unmeasured_values(self):
        rows = [row("n", 13.00, 13.40), row("s", 12.60, 13.00)]
        v, why = dl.assess_date(2, met(rows), {"vv": 100.0, "vh": None}, dl.compat_checks(rows)); self.assertIn("VH", v); self.assertNotIn("COMPLETE AOI", v)


class TestMissingBandAndCompatibility(unittest.TestCase):
    def test_slice_without_vh(self):
        rows = [row("n", 13.00, 13.40), row("s", 12.60, 13.00, pols="['VV']")]
        c = dl.compat_checks(rows); self.assertTrue(c["all_have_VV"]); self.assertFalse(c["all_have_VH"]); self.assertFalse(c["same_pols"])
        v, why = dl.assess_date(2, met(rows), {"vv": 100.0, "vh": None}, c)
        self.assertFalse(v.startswith("COMPLETE")); self.assertTrue(any("VH" in w for w in why))

    def test_slice_without_vv(self):
        rows = [row("n", 13.00, 13.40, pols="['HH', 'HV']"), row("s", 12.60, 13.00)]
        c = dl.compat_checks(rows); self.assertFalse(c["all_have_VV"])
        self.assertTrue(any("VV" in w for w in dl.assess_date(2, met(rows), {"vv": None, "vh": None}, c)[1]))

    def test_time_gap_and_ee_metadata_mismatch_fail(self):
        rows = [row("n", 13.00, 13.40, t=0), row("s", 12.60, 13.00, t=600_000)]          # 10 min apart: not adjacent slices of one take
        c = dl.compat_checks(rows); self.assertFalse(c["acquisition_times_compatible"]); self.assertEqual(c["max_slice_time_gap_s"], 600.0)
        self.assertTrue(any("FAILED" in w for w in dl.assess_date(2, met(rows), {"vv": 100.0, "vh": 100.0}, c)[1]))
        ok = [row("n", 13.00, 13.40, t=0), row("s", 12.60, 13.00, t=25000)]
        m1 = [{"crs": "EPSG:4326", "nominal_scale_m": 1.0, "slice_number": 4}, {"crs": "EPSG:4326", "nominal_scale_m": 1.0, "slice_number": 5}]
        c = dl.compat_checks(ok, m1); self.assertTrue(c["same_crs"]); self.assertTrue(c["slice_numbers_consecutive"])
        c = dl.compat_checks(ok, [dict(m1[0]), dict(m1[1], crs="EPSG:32644", slice_number=9)]); self.assertFalse(c["same_crs"]); self.assertFalse(c["slice_numbers_consecutive"])
        c = dl.compat_checks(ok, [{"crs": None}, {"crs": None}]); self.assertIsNone(c["same_crs"])           # not assessable is None, never assumed True


class TestPlatformOrbitSeparation(unittest.TestCase):
    def test_groups_never_mix_platform_orbit_pass_or_date(self):
        rows = [row("a1", 13.0, 13.4), row("a2", 12.6, 13.0), row("b1", 13.0, 13.4, pf="SENTINEL-1B"), row("o1", 13.0, 13.4, ro=33),
                row("p1", 13.0, 13.4, ps="ASCENDING"), row("d1", 13.0, 13.4, d="2021-11-17")]
        g = dl.groups_from_rows(rows)
        self.assertEqual(len(g), 5); self.assertEqual(sorted(len(v) for v in g.values()), [1, 1, 1, 1, 2])
        self.assertEqual([r["id"] for r in g[("2021-11-16", "DESCENDING", 92, "SENTINEL-1A")]], ["a1", "a2"])
        self.assertEqual(sum(len(v) for v in g.values()), len(rows))                                       # every individual record preserved
        self.assertFalse(dl.compat_checks([rows[0], rows[2]])["same_group_key"])                            # 1A + 1B would be flagged
        self.assertFalse(dl.compat_checks([rows[0], rows[3]])["same_group_key"])                            # different relative orbit flagged

    def test_group_props_carry_platform(self):
        self.assertNotEqual(inv.group_query_props("2021-11-16", "DESCENDING", 92, "SENTINEL-1A"), inv.group_query_props("2021-11-16", "DESCENDING", 92, "SENTINEL-1B"))


class TestExplicitDateAndScript(unittest.TestCase):
    def test_16_november_explicit(self):
        g = dl.groups_from_rows([row("a", 13.0, 13.4), row("b", 12.6, 13.0)])
        e = dl.explicit_date_status(g, "2021-11-16"); self.assertTrue(e["present"]); self.assertEqual(len(e["groups"]), 1)
        self.assertFalse(dl.explicit_date_status(g, "2021-11-18")["present"])                              # absent dates are never invented

    def test_fingerprint_parse(self):
        self.assertEqual(dl.parse_inventory_fingerprint("- AOI/query fingerprint (cache key): `abc123def456`; x"), "abc123def456")
        self.assertIsNone(dl.parse_inventory_fingerprint("nothing")); self.assertIsNone(dl.parse_inventory_fingerprint(None))

    def test_script_is_read_only_and_safe(self):
        s = (ROOT / "scripts" / "s1_date_level_coverage.py").read_text(encoding="utf-8")
        self.assertIn("inList", s); self.assertIn("group_query_props", s); self.assertIn("--overwrite", s); self.assertIn("not overwritten", s)
        self.assertEqual(s.count("unmask("), 1); self.assertIn("cnt = bc.select(b).count().unmask(0)", s)                  # only the COUNT image is unmasked, never a data band
        self.assertNotIn("df.to_csv", s); self.assertNotIn('INV_STEM}.csv").write', s)                                       # inventory files are only read
        self.assertIn("2021-11-16", s); self.assertNotIn("flood_extent", s)
        self.assertIn("NOT RUN - valid VV/VH shares are n/a", s)                                                           # no invented values when EE is not run


if __name__ == "__main__":
    unittest.main()
