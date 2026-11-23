"""Sentinel-1 scene catalogue search + same-orbit pairing (V2).
Search uses the public ASF Search API (no login needed). Pairing logic is pure Python and unit-tested.
NOT yet executed against the live ASF service (build sandbox has no access) - first real run is on the user's machine."""
from collections import defaultdict
from datetime import date, datetime, timezone
import requests
from .s1_orbits import resolve_orbits

ASF = "https://api.daac.asf.alaska.edu/services/search/param"


def _d(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()


def search_asf(bbox, start, end, timeout=60, raw_sink=None):
    """bbox=(minx,miny,maxx,maxy) WGS84; start/end ISO dates. Returns list of normalised scene dicts."""
    minx, miny, maxx, maxy = bbox
    poly = f"POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))"
    params = {"platform": "S1", "processingLevel": "GRD_HD", "beamMode": "IW", "intersectsWith": poly,
              "start": f"{start}T00:00:00Z", "end": f"{end}T23:59:59Z", "output": "json", "maxResults": 500}
    r = requests.get(ASF, params=params, timeout=timeout, headers={"User-Agent": "chennai-flood-risk/0.2"})
    r.raise_for_status()
    raw = r.json()
    if raw_sink is not None:
        raw_sink(raw)  # V2.1: keep the untouched catalogue response for diagnostics/comparison
    return normalise(raw, bbox)


def normalise(raw, bbox=None):
    """ASF returns [[{...}]] or [{...}]; keep only the fields we need. Coverage = share of bbox inside the footprint."""
    rows = raw[0] if raw and isinstance(raw[0], list) else raw
    out = []
    box = None
    if bbox:
        from shapely.geometry import box as _box
        box = _box(*bbox)
    for g in rows or []:
        cov = None
        if box is not None and g.get("stringFootprint"):
            try:
                from shapely import wkt
                cov = round(100 * wkt.loads(g["stringFootprint"]).intersection(box).area / box.area, 1)
            except Exception:
                cov = None
        o = resolve_orbits(g)
        out.append({"scene": o["clean_name"] or g.get("sceneName") or g.get("granuleName") or g.get("fileID"),
                    "granule": g.get("granuleName") or g.get("fileID"), "date": _d(g["startTime"]).isoformat(),
                    "time_utc": g["startTime"], "platform": g.get("platform") or o["platform_code"],
                    "direction": g.get("flightDirection"), "abs_orbit": o["abs_orbit"],
                    "abs_orbit_source": o["abs_orbit_source"], "rel_orbit": o["rel_orbit"],
                    "rel_orbit_source": o["rel_orbit_source"], "rel_orbit_catalogue": o["rel_orbit_catalogue"],
                    "rel_orbit_derived": o["rel_orbit_derived"], "orbit_conflict": o["orbit_conflict"],
                    "polarization": g.get("polarization"), "coverage_pct": cov})
    return sorted(out, key=lambda r: r["time_utc"])


def pair_scenes(scenes, pre, post, peak, min_pre=3, min_coverage=95.0, max_post_lag_days=10):
    """Choose ONE (direction, relative orbit) with scenes in both windows - never mix orbits, because
    backscatter depends on viewing geometry. Returns a verdict dict.
    pre/post: (start,end) ISO dates. peak: ISO date of the event's heaviest rain/flooding."""
    pre = tuple(_d(x) for x in pre)
    post = tuple(_d(x) for x in post)
    peak = _d(peak)
    groups = defaultdict(lambda: {"pre": [], "post": []})
    unknown_orbit = 0
    for s in scenes:
        if s.get("coverage_pct") is not None and s["coverage_pct"] < min_coverage:
            continue
        if not s.get("direction") or s.get("rel_orbit") in (None, "", 0):
            unknown_orbit += 1      # V2.1: a scene with unknown direction/relative orbit is NEVER paired (V2.0 grouped them together)
            continue
        d = _d(s["date"])
        key = (s["direction"], s["rel_orbit"])
        if pre[0] <= d <= pre[1]:
            groups[key]["pre"].append(s)
        elif post[0] <= d <= post[1] and d >= peak:
            groups[key]["post"].append(s)
    cands = []
    for key, g in groups.items():
        if not g["pre"] or not g["post"]:
            continue
        first_post = min(_d(s["date"]) for s in g["post"])
        lag = (first_post - peak).days
        cands.append((lag > max_post_lag_days, lag, -len(g["pre"]), key, g))
    if not cands:
        why = "no single (direction, relative orbit) has scenes in BOTH windows (full coverage, post on/after peak)"
        if unknown_orbit:
            why += f"; {unknown_orbit} scene(s) excluded because direction or relative orbit is unknown"
        return {"verdict": "NOT PROCESSABLE", "reason": why, "orbit": None, "excluded_unknown_orbit": unknown_orbit}
    cands.sort(key=lambda c: c[:3])
    late, lag, _, key, g = cands[0]
    n_pre = len(g["pre"])
    verdict = "PROCESSABLE" if (n_pre >= min_pre and not late) else "MARGINAL"
    why = []
    if n_pre < min_pre:
        why.append(f"only {n_pre} pre-event scene(s) (<{min_pre}): weak baseline")
    if late:
        why.append(f"first post-event scene is {lag} days after peak (>{max_post_lag_days}): water may have receded")
    return {"verdict": verdict, "reason": "; ".join(why) or "ok", "orbit": {"direction": key[0], "rel_orbit": key[1]},
            "pre_scenes": [s["scene"] for s in g["pre"]], "post_scenes": [s["scene"] for s in g["post"]],
            "pre_dates": [s["date"] for s in g["pre"]], "post_dates": [s["date"] for s in g["post"]],
            "days_after_peak": lag, "excluded_unknown_orbit": unknown_orbit,
            "platforms": sorted({str(x.get("platform")) for x in g["pre"] + g["post"]}),
            "rel_orbit_sources": sorted({str(x.get("rel_orbit_source")) for x in g["pre"] + g["post"]}),
            "orbit_conflicts": sum(1 for x in g["pre"] + g["post"] if x.get("orbit_conflict"))}


def _gee_date(ms):
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()


def match_scenes(scenes, gee_items):
    """Compare catalogue scenes (dicts as produced by normalise) with Earth Engine items
    ({'id','rel','abs','pass','plat','pol','t'}). Pure function; the Earth Engine query itself is in scripts/s1_gee_check.py.
    A scene is FOUND only if an item exists: exact system:index match, else same UTC date + same absolute orbit."""
    by_id = {g["id"]: g for g in gee_items}
    by_key = {}
    for g in gee_items:
        if g.get("t") is not None and g.get("abs") is not None:
            by_key[(_gee_date(g["t"]), int(g["abs"]))] = g
    rows = []
    for s in scenes:
        g, how = by_id.get(s.get("scene")), "exact system:index"
        if g is None:
            ao = s.get("abs_orbit")
            g = by_key.get((s["date"], int(ao))) if ao not in (None, "") and ao == ao else None
            how = "date + absolute orbit (id differs)" if g else ""
        row = {"scene": s.get("scene"), "date": s["date"], "catalogue_direction": s.get("direction"),
               "abs_orbit": s.get("abs_orbit"), "catalogue_rel_orbit": s.get("rel_orbit_catalogue"),
               "derived_rel_orbit": s.get("rel_orbit_derived"), "status": "FOUND" if g else "NOT FOUND IN EARTH ENGINE",
               "match_method": how, "gee_id": g["id"] if g else "", "gee_rel_orbit": g.get("rel") if g else None,
               "gee_abs_orbit": g.get("abs") if g else None, "gee_pass": g.get("pass") if g else None,
               "gee_platform": g.get("plat") if g else None, "gee_polarisation": str(g.get("pol")) if g else ""}
        def same(a, b):
            return None if a in (None, "") or b in (None, "") or a != a or b != b else int(a) == int(b)
        row["derived_matches_gee"] = same(row["derived_rel_orbit"], row["gee_rel_orbit"])
        row["catalogue_matches_gee"] = same(row["catalogue_rel_orbit"], row["gee_rel_orbit"])
        row["direction_matches_gee"] = (None if not g or not s.get("direction") else
                                        str(s["direction"]).upper() == str(g.get("pass")).upper())
        rows.append(row)
    return rows
