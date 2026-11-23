"""V2.3 window scan: classify Earth Engine Sentinel-1 candidates against a reference acquisition geometry.
Pure-Python logic (unit-tested on SYNTHETIC rows). Earth Engine querying lives in scripts/s1_window_scan.py (untested until run live)."""
from .s1_orbits import parse_scene_name, relative_from_absolute


def classify(item, ref, min_cov=95.0, min_valid=90.0, angle_tol_deg=1.0):
    """item/ref keys: id, rel_orbit, pass, platform, mode, pols, coverage_pct, valid_pct, angle_mean.
    Returns (verdict, reasons). COMPATIBLE = same platform, IW, VV, same pass and relative orbit, coverage/valid OK, mean incidence angle within tol."""
    why = []
    if item.get("mode") != "IW":
        why.append(f"mode {item.get('mode')} != IW")
    if "VV" not in str(item.get("pols")):
        why.append("no VV")
    cov, val = item.get("coverage_pct"), item.get("valid_pct")
    if cov is None or cov < min_cov:
        why.append(f"study-area coverage {cov} % < {min_cov} %")
    if val is None or val < min_valid:
        why.append(f"valid pixels {val} % < {min_valid} %")
    geom = []
    if item.get("pass") != ref["pass"]:
        geom.append(f"pass {item.get('pass')} != {ref['pass']}")
    if item.get("rel_orbit") != ref["rel_orbit"]:
        geom.append(f"relative orbit {item.get('rel_orbit')} != {ref['rel_orbit']}")
    if item.get("platform") != ref["platform"]:
        geom.append(f"platform {item.get('platform')} != {ref['platform']} (different calibration/orbit offsets)")
    a, ra = item.get("angle_mean"), ref.get("angle_mean")
    if not geom and a is not None and ra is not None and abs(a - ra) > angle_tol_deg:
        geom.append(f"mean incidence angle {a:.1f} vs {ra:.1f} deg differs > {angle_tol_deg}")
    if geom:
        verdict = "DIFFERENT GEOMETRY (not directly comparable)"
    elif why:
        verdict = "SAME GEOMETRY BUT UNUSABLE"
    else:
        verdict = "COMPATIBLE"
    return verdict, why + geom


def derived_rel(item_id):
    i = parse_scene_name(item_id)
    return relative_from_absolute(i["platform_code"], i["abs_orbit"])[0] if i else None


def expected_cycle_dates(ref_date, start, end, repeat_days=12):
    """Dates on the 12-day repeat grid of ONE satellite (S1A alone in 2015; S1B launched 2016) inside [start, end]. A planning aid, NOT availability."""
    from datetime import date, timedelta
    r, s, e = (date.fromisoformat(x) for x in (ref_date, start, end))
    k = -((r - s).days // repeat_days)
    d = r + timedelta(days=repeat_days * k)
    out = []
    while d <= e:
        if d >= s:
            out.append(d.isoformat())
        d += timedelta(days=repeat_days)
    return out
