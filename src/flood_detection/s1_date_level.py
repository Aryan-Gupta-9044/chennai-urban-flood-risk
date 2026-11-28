"""M4B - date-level (multi-slice) Sentinel-1 coverage verification. METADATA / lightweight only: no imagery download, no preprocessing,
no flood classification. Pure helpers (shapely/pandas only, testable offline); the Earth Engine part lives in scripts/s1_date_level_coverage.py.

Definitions
  group          = (UTC date, pass direction, relative orbit, platform): the same key as s1_inventory.group_key. Sentinel-1A and 1B, or different
                   orbits/passes, are NEVER one group.
  footprint cov. = share of the AOI polygon covered by the UNION of the slice footprints (each AOI area counted once; overlap not double counted).
  overlap        = AOI area covered by >= 2 slice footprints; gap = AOI area covered by NO slice footprint.
  valid VV / VH  = share of AOI pixels (30 m sampling) unmasked in >= 1 slice (from a per-pixel image COUNT, never a value fill).
A footprint is the product outline; the valid-pixel share is the stricter, pixel-level measure. Both are reported; neither is a flood product."""
import json
import re
from itertools import combinations

from . import s1_inventory as inv

ADJACENT_SLICE_MAX_GAP_S = 120.0    # adjacent GRD slices of one data-take start ~25 s apart; a larger gap suggests a different take
THRESHOLDS = {"min_footprint_pct": 99.9, "min_valid_pct": 95.0, "cross_check_pp": 1.0}


def groups_from_rows(rows):
    """{group_key: [row, ...]} for ALL groups (single-slice groups included). Individual rows are never merged or altered."""
    g = {}
    for r in rows:
        g.setdefault(inv.group_key(r), []).append(r)
    return dict(sorted(g.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2] if kv[0][2] is not None else -1, str(kv[0][3]))))


def footprint_geom(fp):
    """Shapely geometry from a footprint GeoJSON string/dict, or None."""
    from shapely.geometry import shape
    if fp is None or (isinstance(fp, float)) or fp == "":
        return None
    d = json.loads(fp) if isinstance(fp, str) else fp
    g = shape(d)
    return g if g.is_valid else g.buffer(0)


def footprint_metrics(aoi_wgs, geoms, area_crs="EPSG:32644"):
    """Coverage / overlap / gap of the AOI by slice footprints; areas in an equal-distance projected CRS (UTM 44N covers Chennai).
    A missing footprint (None) makes the result None for that slice and the combined values are then NOT computed (never a silent partial)."""
    import geopandas as gpd
    if not geoms or any(g is None for g in geoms):
        return None
    P = lambda g: gpd.GeoSeries([g], crs=4326).to_crs(area_crs).iloc[0]   # noqa: E731
    aoi = P(aoi_wgs); A = aoi.area
    sl = [P(g).intersection(aoi) for g in geoms]
    union = sl[0]
    for s in sl[1:]:
        union = union.union(s)
    ov = None
    for x, y in combinations(sl, 2):
        i = x.intersection(y)
        ov = i if ov is None else ov.union(i)
    ov_a = ov.area if ov is not None else 0.0
    gap_a = max(A - union.area, 0.0)
    pct = lambda v: round(100.0 * v / A, 4)   # noqa: E731
    return {"aoi_km2": round(A / 1e6, 3), "slice_coverage_pct": [pct(s.area) for s in sl], "combined_footprint_pct": pct(union.area),
            "overlap_pct_of_aoi": pct(ov_a), "overlap_km2": round(ov_a / 1e6, 4), "gap_pct_of_aoi": pct(gap_a), "gap_km2": round(gap_a / 1e6, 4),
            "sum_of_slices_pct": round(sum(pct(s.area) for s in sl), 4)}


def time_gap_seconds(rows):
    """Largest gap (s) between consecutive slice start times (field `t`, ms since epoch), or None."""
    ts = sorted(r["t"] for r in rows if r.get("t") is not None)
    return None if len(ts) < 2 else round(max((b - a) / 1000.0 for a, b in zip(ts, ts[1:])), 1)


def pol_set(p):
    """Sorted tuple of polarisation names in a list or its string form."""
    q = str(p).upper()
    return tuple(b for b in ("HH", "HV", "VH", "VV") if b in q)


def compat_checks(rows, meta=None):
    """Compatibility of the slices of ONE group. rows = inventory rows; meta = optional per-slice Earth Engine metadata dicts (same order/ids)
    with crs, nominal_scale_m, abs_orbit_start/stop, cycle, config_id, resolution_m, slice_number, total_slices (None where EE gave none).
    Each check is True / False / None (None = not assessable from the data at hand, never assumed True)."""
    k = {inv.group_key(r) for r in rows}
    out = {"same_group_key": len(k) == 1,
           "same_pols": len({pol_set(r["pols"]) for r in rows}) == 1,
           "all_have_VV": all(inv.pol_flags(r["pols"])["has_VV"] for r in rows), "all_have_VH": all(inv.pol_flags(r["pols"])["has_VH"] for r in rows),
           "same_abs_orbit": len({r.get("abs_orbit") for r in rows}) == 1 if all(r.get("abs_orbit") is not None for r in rows) else None}
    gap = time_gap_seconds(rows); out["max_slice_time_gap_s"] = gap
    out["acquisition_times_compatible"] = None if gap is None else gap <= ADJACENT_SLICE_MAX_GAP_S
    def same(key):
        if not meta or any(m.get(key) is None for m in meta):
            return None
        return len({str(m[key]) for m in meta}) == 1
    out["same_crs"] = same("crs"); out["same_nominal_scale"] = same("nominal_scale_m"); out["same_cycle"] = same("cycle")
    out["same_instrument_config"] = same("config_id"); out["same_resolution"] = same("resolution_m")
    sn = [m.get("slice_number") for m in (meta or [])]
    out["slice_numbers_consecutive"] = (None if not meta or any(x is None for x in sn) else sorted(int(x) for x in sn) == list(range(int(min(sn)), int(min(sn)) + len(sn))))
    return out


def assess_date(n_slices, fmet, valid, compat, thr=None):
    """Verdict for one date-level observation. valid = {'vv': pct|None, 'vh': pct|None} from the pixel check (None = not measured).
    'COMPLETE' only when footprint union, VV and VH valid shares all meet the thresholds and no compatibility check FAILED.
    Anything unmeasured is reported as not assessed, never assumed fine."""
    t = dict(THRESHOLDS, **(thr or {})); why = []
    if fmet is None:
        return "NOT ASSESSED (slice footprint missing)", ["slice footprint missing"]
    if fmet["combined_footprint_pct"] < t["min_footprint_pct"]:
        why.append(f"combined footprint covers {fmet['combined_footprint_pct']} % of the AOI (gap {fmet['gap_pct_of_aoi']} % = {fmet['gap_km2']} km2)")
    if not compat.get("all_have_VV"): why.append("not every slice has VV")
    if not compat.get("all_have_VH"): why.append("not every slice has VH")
    failed = [k for k, v in compat.items() if v is False and k not in ("all_have_VV", "all_have_VH")]
    if failed: why.append("compatibility FAILED: " + ", ".join(failed))
    unmeasured = []
    for b in ("vv", "vh"):
        v = valid.get(b)
        if v is not None and v > fmet["combined_footprint_pct"] + t["cross_check_pp"]:
            why.append(f"valid {b.upper()} {v} % exceeds the footprint coverage {fmet['combined_footprint_pct']} % - inconsistent, investigate (not accepted)")
            continue
        if v is None: unmeasured.append(b.upper())
        elif v < t["min_valid_pct"]: why.append(f"combined valid {b.upper()} {v} % < {t['min_valid_pct']} %")
    if why:
        return "PARTIAL / NOT COMPLETE AOI COVERAGE", why + ([f"valid {'/'.join(unmeasured)} not measured"] if unmeasured else [])
    if unmeasured:
        return f"FOOTPRINT COMPLETE; PIXEL VALIDITY NOT MEASURED ({'/'.join(unmeasured)})", [f"valid {'/'.join(unmeasured)} not measured (needs the Earth Engine check)"]
    return "COMPLETE AOI COVERAGE (footprint and valid VV/VH)" if n_slices >= 1 else "NOT ASSESSED", []


def explicit_date_status(groups, date_str):
    """Is `date_str` present in the inventory groups? Never invents a missing date."""
    hit = [k for k in groups if k[0] == date_str]
    return {"date": date_str, "present": bool(hit), "groups": hit}


def parse_inventory_fingerprint(md_text):
    m = re.search(r"AOI/query fingerprint \(cache key\): `([0-9a-f]{6,64})`", md_text or "")
    return m.group(1) if m else None
