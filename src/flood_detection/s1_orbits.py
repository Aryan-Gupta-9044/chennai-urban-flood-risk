"""Sentinel-1 orbit-number helpers (V2.1).

ABSOLUTE orbit  = running orbit count since launch (appears in the product name, e.g. ..._008564_...).
RELATIVE orbit  = track number 1..175 inside the 175-orbit / 12-day repeat cycle. Acquisitions can be paired only if they
                  share direction AND relative orbit (same viewing geometry).

Relative orbit is taken from catalogue metadata when present. When it is missing, it is DERIVED from the absolute orbit with
the ESA formula (ESA SentiWiki, "Sentinel-1 products", https://sentiwiki.copernicus.eu/web/s1-products):
    S-1A: relative = mod(absolute - 73, 175) + 1
    S-1B: relative = mod(absolute - 27, 175) + 1
The mission-specific offset matters: plain `absolute mod 175` (no offset, no +1) is NOT the relative orbit.
S-1C / S-1D are deliberately NOT derived here: their offsets are published as changing/provisional (ESA lists S-1C offset 172 until
2026-06-24 and 99 afterwards; S-1D 42 marked provisional) and they are irrelevant to 2015-2023 events. Unknown stays unknown (None).
The derived value is cross-checked against Earth Engine's `relativeOrbitNumber_start` by scripts/s1_gee_check.py."""
import re

CYCLE = 175
OFFSETS = {"S1A": 73, "S1B": 27}
FORMULA_SOURCE = "ESA SentiWiki S1 products: S1A mod(abs-73,175)+1; S1B mod(abs-27,175)+1"
NAME_RE = re.compile(r"(S1[ABCD])_([A-Z0-9]{2})_([A-Z0-9_]{4})_([0-9A-Z]{4})_(\d{8})T(\d{6})_(\d{8})T(\d{6})_(\d{6})_([0-9A-F]{6})_([0-9A-F]{4})")
ABS_KEYS = ("orbit", "absoluteOrbit", "absoluteOrbitNumber")
REL_KEYS = ("pathNumber", "relativeOrbit", "relativeOrbitNumber", "track", "path")


def parse_scene_name(name):
    """Parse a Sentinel-1 product name (ASF suffixes such as -GRD_HD / .SAFE / .zip are ignored). Returns dict or None."""
    m = NAME_RE.search(str(name or ""))
    if not m:
        return None
    g = m.groups()
    return {"platform_code": g[0], "mode": g[1], "product": g[2], "start_date": g[4], "abs_orbit": int(g[8]),
            "clean_name": m.group(0)}


def relative_from_absolute(platform_code, abs_orbit):
    """Returns (relative_orbit or None, note)."""
    if abs_orbit is None:
        return None, "no absolute orbit"
    if platform_code in OFFSETS:
        return (int(abs_orbit) - OFFSETS[platform_code]) % CYCLE + 1, "derived: " + FORMULA_SOURCE
    return None, f"no documented stable offset for {platform_code or 'unknown platform'} - not derived"


def _as_int(v, lo=None, hi=None):
    try:
        x = int(float(v))
    except (TypeError, ValueError):
        return None
    if lo is not None and x < lo:
        return None
    if hi is not None and x > hi:
        return None
    return x


def platform_code_from(record_platform, name_info):
    if name_info:
        return name_info["platform_code"]
    p = str(record_platform or "").upper().replace("SENTINEL-", "S").replace("-", "")
    return p if p in ("S1A", "S1B", "S1C", "S1D") else None


def resolve_orbits(rec):
    """rec = raw catalogue record (dict). Returns dict with abs/rel orbit, their sources and a conflict flag."""
    name = rec.get("sceneName") or rec.get("granuleName") or rec.get("fileID") or rec.get("fileName")
    info = parse_scene_name(name) or parse_scene_name(rec.get("granuleName"))
    plat = platform_code_from(rec.get("platform"), info)
    abs_o, abs_src = None, "missing"
    for k in ABS_KEYS:
        v = _as_int(rec.get(k), lo=1)
        if v is not None:
            abs_o, abs_src = v, f"catalogue:{k}"
            break
    if abs_o is None and info:
        abs_o, abs_src = info["abs_orbit"], "parsed from scene name"
    cat_rel, cat_key = None, None
    for k in REL_KEYS:
        v = _as_int(rec.get(k), lo=1, hi=CYCLE)   # 0, blank or out-of-range = treated as missing
        if v is not None:
            cat_rel, cat_key = v, k
            break
    der_rel, der_note = relative_from_absolute(plat, abs_o)
    if cat_rel is not None:
        rel, src = cat_rel, f"catalogue:{cat_key}"
    elif der_rel is not None:
        rel, src = der_rel, f"derived from absolute orbit ({plat}, ESA formula)"
    else:
        rel, src = None, "missing: " + der_note
    return {"platform_code": plat, "abs_orbit": abs_o, "abs_orbit_source": abs_src, "rel_orbit": rel,
            "rel_orbit_source": src, "rel_orbit_catalogue": cat_rel, "rel_orbit_derived": der_rel,
            "orbit_conflict": bool(cat_rel is not None and der_rel is not None and cat_rel != der_rel),
            "clean_name": info["clean_name"] if info else None}
