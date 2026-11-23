"""Orbit extraction / pairing tests (V2.1).
Real facts used (from the user's Windows ASF run): five Nov 2015 scenes, all DESCENDING Sentinel-1A, 100% coverage,
dates 20150820, 20150901, 20151019, 20151031, 20151112 with absolute orbits 7339, 7514, 8214, 8389, 8564, rel_orbit blank in ASF output.
PLACEHOLDERS: the time-of-day and 4-hex suffixes inside the scene names below are invented (not reported to me).
The December 2015 scene list was NOT reported to me: Dec tests are either HYPOTHETICAL (labelled) or driven by an optional
fixture file tests/fixtures/s1_scenes_2015_dec.csv (skipped when absent)."""
import csv
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.flood_detection import s1_catalog as cat
from src.flood_detection.s1_orbits import parse_scene_name, relative_from_absolute, resolve_orbits

NOV = [("20150820", 7339), ("20150901", 7514), ("20151019", 8214), ("20151031", 8389), ("20151112", 8564)]
FIX = Path(__file__).parent / "fixtures" / "s1_scenes_2015_dec.csv"


def raw(date, absorbit, plat="S1A", direction="DESCENDING", path=None, cov_wkt=True):
    name = f"{plat}_IW_GRDH_1SDV_{date}T005800_{date}T005825_{absorbit:06d}_00AAAA_BBBB"
    r = {"granuleName": name + "-GRD_HD", "startTime": f"{date[:4]}-{date[4:6]}-{date[6:]}T00:58:00Z",
         "platform": f"Sentinel-{plat[1:]}", "flightDirection": direction, "polarization": "VV+VH"}
    if path is not None:
        r["pathNumber"] = path
    if cov_wkt:
        r["stringFootprint"] = "POLYGON((78 11,82 11,82 15,78 15,78 11))"
    return r


BBOX = (80.14, 12.85, 80.33, 13.24)


def nov_scenes(**kw):
    return cat.normalise([raw(d, a, **kw) for d, a in NOV], BBOX)


class Orbits(unittest.TestCase):
    def test_esa_formula(self):
        self.assertEqual(relative_from_absolute("S1A", 73)[0], 1)
        self.assertEqual(relative_from_absolute("S1A", 247)[0], 175)
        self.assertEqual(relative_from_absolute("S1A", 248)[0], 1)
        self.assertEqual(relative_from_absolute("S1B", 27)[0], 1)
        self.assertEqual(relative_from_absolute("S1B", 201)[0], 175)

    def test_not_plain_modulo(self):
        # abs mod 175 == 164 for all five scenes, but that is NOT the ESA relative orbit definition
        for _, a in NOV:
            self.assertEqual(a % 175, 164)
            self.assertNotEqual(relative_from_absolute("S1A", a)[0], 164)

    def test_c_and_d_not_derived(self):
        self.assertIsNone(relative_from_absolute("S1C", 5000)[0])
        self.assertIsNone(relative_from_absolute("S1D", 5000)[0])

    def test_name_parser_ignores_asf_suffix(self):
        for suffix in ("", "-GRD_HD", ".SAFE", ".zip"):
            p = parse_scene_name("S1A_IW_GRDH_1SDV_20151112T005800_20151112T005825_008564_00AAAA_BBBB" + suffix)
            self.assertEqual((p["platform_code"], p["abs_orbit"]), ("S1A", 8564))
            self.assertFalse(p["clean_name"].endswith(("-GRD_HD", ".SAFE", ".zip")))

    def test_nov2015_all_five_same_derived_orbit_and_source(self):
        sc = nov_scenes()
        self.assertEqual(len(sc), 5)
        self.assertEqual({s["rel_orbit"] for s in sc}, {92})                       # ESA formula, same for all five
        self.assertEqual([s["abs_orbit"] for s in sc], [a for _, a in NOV])
        for s in sc:
            self.assertIsNone(s["rel_orbit_catalogue"])
            self.assertTrue(s["rel_orbit_source"].startswith("derived"))
            self.assertEqual(s["coverage_pct"], 100.0)
            self.assertFalse(s["orbit_conflict"])

    def test_catalogue_preferred_and_conflict_flagged(self):
        s = cat.normalise([raw("20150820", 7339, path=164)], BBOX)[0]
        self.assertEqual(s["rel_orbit"], 164)                                      # catalogue wins ...
        self.assertTrue(s["rel_orbit_source"].startswith("catalogue"))
        self.assertEqual(s["rel_orbit_derived"], 92)
        self.assertTrue(s["orbit_conflict"])                                       # ... but the disagreement is recorded

    def test_zero_or_blank_catalogue_value_is_missing(self):
        for v in (0, "", None):
            s = cat.normalise([raw("20150820", 7339, path=v)], BBOX)[0]
            self.assertEqual(s["rel_orbit"], 92)

    def test_absolute_orbit_from_catalogue_key_preferred_over_name(self):
        r = raw("20150820", 7339)
        r["orbit"] = 7339
        self.assertEqual(cat.normalise([r], BBOX)[0]["abs_orbit_source"], "catalogue:orbit")


class Pairing(unittest.TestCase):
    PRE, POST, PEAK = ("2015-08-15", "2015-11-05"), ("2015-11-10", "2015-11-20"), "2015-11-10"

    def test_nov2015_event(self):
        r = cat.pair_scenes(nov_scenes(), self.PRE, self.POST, self.PEAK)
        self.assertEqual(r["verdict"], "PROCESSABLE")
        self.assertEqual(r["orbit"], {"direction": "DESCENDING", "rel_orbit": 92})
        self.assertEqual(r["pre_dates"], ["2015-08-20", "2015-09-01", "2015-10-19", "2015-10-31"])
        self.assertEqual(r["post_dates"], ["2015-11-12"])
        self.assertEqual(r["days_after_peak"], 2)
        self.assertEqual(r["platforms"], ["Sentinel-1A"])

    def test_requires_direction_and_relative_orbit(self):
        sc = nov_scenes()
        post_other_dir = cat.normalise([raw("20151112", 8564, direction="ASCENDING")], BBOX)
        r = cat.pair_scenes(sc[:4] + post_other_dir, self.PRE, self.POST, self.PEAK)
        self.assertEqual(r["verdict"], "NOT PROCESSABLE")                           # same rel orbit, wrong direction
        other_rel = cat.normalise([raw("20151112", 8564 + 1)], BBOX)               # next absolute orbit => different relative orbit
        r = cat.pair_scenes(sc[:4] + other_rel, self.PRE, self.POST, self.PEAK)
        self.assertEqual(r["verdict"], "NOT PROCESSABLE")                           # same direction, wrong relative orbit

    def test_unknown_orbit_scenes_are_never_grouped(self):
        sc = nov_scenes()
        for s in sc:
            s["rel_orbit"] = None
        r = cat.pair_scenes(sc, self.PRE, self.POST, self.PEAK)
        self.assertEqual(r["verdict"], "NOT PROCESSABLE")                           # V2.0 would have grouped them under (DESC, None)
        self.assertEqual(r["excluded_unknown_orbit"], 5)
        self.assertIn("unknown", r["reason"])

    # ---- December 2015 -------------------------------------------------------------------------------------------
    def test_dec2015_HYPOTHETICAL_cadence(self):
        """HYPOTHETICAL scenes (not observed data): the same orbit repeats every 12 days: 24 Nov, 6 Dec, 18 Dec.
        Tests only the verdict logic for the Dec-2015 window of config/s1_events.json (pre 15 Oct-5 Nov, post 2-14 Dec, peak 2 Dec)."""
        extra = cat.normalise([raw("20151206", 8564 + 2 * 175)], BBOX)  # same relative orbit, 6 Dec
        self.assertEqual(extra[0]["rel_orbit"], 92)
        r = cat.pair_scenes(nov_scenes() + extra, ("2015-10-15", "2015-11-05"), ("2015-12-02", "2015-12-14"), "2015-12-02")
        self.assertEqual(r["verdict"], "MARGINAL")                                  # only 2 pre-window scenes (19 Oct, 31 Oct)
        self.assertIn("weak baseline", r["reason"])
        self.assertEqual(r["days_after_peak"], 4)

    @unittest.skipUnless(FIX.exists(), "tests/fixtures/s1_scenes_2015_dec.csv not provided (Dec 2015 scenes not yet reported)")
    def test_dec2015_real_scene_list_invariants(self):
        rows = list(csv.DictReader(open(FIX, encoding="utf-8")))
        sc = []
        for r in rows:
            o = resolve_orbits({"granuleName": r.get("granule") or r["scene"], "platform": r.get("platform"),
                                "pathNumber": r.get("rel_orbit_catalogue") or None})
            sc.append({"scene": o["clean_name"] or r["scene"], "date": r["date"], "time_utc": r["time_utc"], "platform": r.get("platform"),
                       "direction": r["direction"], "rel_orbit": o["rel_orbit"], "coverage_pct": float(r["coverage_pct"] or 0),
                       "orbit_conflict": o["orbit_conflict"], "rel_orbit_source": o["rel_orbit_source"]})
        res = cat.pair_scenes(sc, ("2015-10-15", "2015-11-05"), ("2015-12-02", "2015-12-14"), "2015-12-02")
        if res["orbit"]:
            chosen = {(s["direction"], s["rel_orbit"]) for s in sc if s["scene"] in res["pre_scenes"] + res["post_scenes"]}
            self.assertEqual(len(chosen), 1)
            self.assertNotIn(None, [k[1] for k in chosen])


class EarthEngineMatching(unittest.TestCase):
    """Logic only, with HAND-MADE Earth Engine items. NO Earth Engine query has been run."""

    def items(self):
        sc = nov_scenes()
        out = []
        for s in sc[:3]:      # pretend only the first three exist in Earth Engine
            out.append({"id": s["scene"], "rel": 92, "abs": s["abs_orbit"], "pass": "DESCENDING", "plat": "A", "pol": ["VV", "VH"],
                        "t": 1.0})
        return sc, out

    def test_found_and_not_found(self):
        sc, items = self.items()
        rows = cat.match_scenes(sc, items)
        self.assertEqual([r["status"] for r in rows], ["FOUND"] * 3 + ["NOT FOUND IN EARTH ENGINE"] * 2)
        self.assertTrue(all(r["derived_matches_gee"] for r in rows[:3]))
        self.assertIsNone(rows[3]["derived_matches_gee"])

    def test_orbit_disagreement_is_reported(self):
        sc, items = self.items()
        for it in items:
            it["rel"] = 164          # if Earth Engine said 164, the derived value must be reported as NOT matching
        rows = cat.match_scenes(sc, items)
        self.assertTrue(all(r["derived_matches_gee"] is False for r in rows[:3]))

    def test_match_by_date_and_absolute_orbit_when_id_differs(self):
        sc, items = self.items()
        from datetime import datetime, timezone
        for it, s in zip(items, sc):
            it["id"] = "different_id"
            it["t"] = datetime.fromisoformat(s["date"] + "T00:58:00+00:00").timestamp() * 1000
        rows = cat.match_scenes(sc, items)
        self.assertEqual([r["match_method"] for r in rows[:3]], ["date + absolute orbit (id differs)"] * 3)


if __name__ == "__main__":
    unittest.main()
