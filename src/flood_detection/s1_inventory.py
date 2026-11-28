"""V2.3 acquisition-inventory helpers (pure Python, unit-tested on synthetic rows). Earth Engine access is in scripts/s1_inventory.py (untested until run live)."""
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def month_windows(start, end):
    """Calendar-month [start, end) windows covering [start, end) (ISO dates) - keeps every getInfo() small."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while s < e:
        nxt = date(s.year + (s.month == 12), s.month % 12 + 1, 1)
        out.append((s.isoformat(), min(nxt, e).isoformat()))
        s = nxt
    return out


def utc_ist(t_ms):
    u = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
    return u.isoformat(timespec="seconds"), u.astimezone(IST).isoformat(timespec="seconds")


def dedupe(items):
    """Same system:index returned by two month windows (window edge) -> keep one."""
    seen, out = set(), []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"]); out.append(it)
    return out


def group_key(it):
    return (it["date_utc"][:10], it["pass"], it["rel_orbit"], it["platform"])


def slice_groups(rows):
    """Acquisitions split into several slices on the same date/orbit (the AOI may straddle a slice boundary).
    Returns {key: [ids]} only for keys with > 1 image - per-image coverage is then NOT the date's coverage."""
    g = {}
    for r in rows:
        g.setdefault(group_key(r), []).append(r["id"])
    return {k: v for k, v in g.items() if len(v) > 1}


def candidate_table(cands, rows, ref):
    """One row per configured candidate date: FOUND (compatible / other geometry / unusable) or NOT FOUND in the queried rows."""
    out = []
    for c in cands:
        hit = [r for r in rows if r["date_utc"][:10] == c["date"]]
        same = [r for r in hit if r["pass"] == ref["pass"] and r["rel_orbit"] == ref["rel_orbit"] and r["platform"] == ref["platform"]]
        if not hit:
            res, ids = "NOT FOUND in queried collection/window", ""
        elif not same:
            res, ids = "FOUND ONLY WITH OTHER GEOMETRY", "; ".join(r["id"] for r in hit)
        else:
            res = "FOUND " + "/".join(sorted({r["verdict"] for r in same}))
            ids = "; ".join(r["id"] for r in same)
        out.append({**c, "result": res, "ids": ids, "n_images_that_date": len(hit)})
    return out


def compatible_by_month(rows):
    m = {}
    for r in rows:
        if r.get("verdict") == "COMPATIBLE":
            m.setdefault(r["date_utc"][:7], []).append(r["date_utc"][:10])
    return {k: sorted(v) for k, v in sorted(m.items())}


# ---------------------------------------------------------------- M4-A additions (pure helpers; metadata only)
def pol_flags(pols):
    """VV / VH availability from the Earth Engine transmitterReceiverPolarisation property (list like ['VV','VH'] or a string)."""
    s = [str(p).upper() for p in pols] if isinstance(pols, (list, tuple)) else [p for p in str(pols).replace("[", " ").replace("]", " ").replace("'", " ").replace(",", " ").upper().split()]
    vv, vh = "VV" in s, "VH" in s
    return {"has_VV": vv, "has_VH": vh, "dual_pol_VV_VH": vv and vh}


def round_geojson(geom, nd=5):
    """Round GeoJSON coordinates (footprints) so the cached/CSV text stays small; returns a compact JSON string, or '' if no geometry."""
    import json
    if not geom:
        return ""
    def r(x):
        return round(x, nd) if isinstance(x, (int, float)) else [r(i) for i in x]
    return json.dumps({"type": geom.get("type"), "coordinates": r(geom.get("coordinates", []))}, separators=(",", ":"))


def geometry_summary(rows):
    """One row per (pass, relative orbit, platform): scene count, date range, VV/VH availability, mean/min AOI coverage and valid share.
    Nothing is dropped: scenes with incomplete AOI coverage are counted and their number reported separately."""
    g = {}
    for r in rows:
        g.setdefault((r["pass"], r["rel_orbit"], r["platform"]), []).append(r)
    out = []
    for (ps, ro, pf), rs in sorted(g.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] if kv[0][1] is not None else -1, str(kv[0][2]))):
        cov = [x["coverage_pct"] for x in rs if x.get("coverage_pct") is not None]
        val = [x["valid_pct"] for x in rs if x.get("valid_pct") is not None]
        dates = sorted({x["date_utc"][:10] for x in rs})
        out.append({"pass": ps, "rel_orbit": ro, "platform": pf, "n_scenes": len(rs), "n_acquisition_dates": len(dates),
                    "first_date": dates[0], "last_date": dates[-1],
                    "n_with_VV": sum(1 for x in rs if x.get("has_VV", True)), "n_with_VH": sum(1 for x in rs if x.get("has_VH")),
                    "n_dual_pol": sum(1 for x in rs if x.get("dual_pol_VV_VH")),
                    "n_incomplete_aoi_coverage": sum(1 for c in cov if c < 95.0), "min_coverage_pct": min(cov) if cov else None,
                    "mean_coverage_pct": round(sum(cov) / len(cov), 2) if cov else None, "mean_valid_pct": round(sum(val) / len(val), 2) if val else None})
    return out


def assess_without_reference(item, min_cov=95.0, min_valid=90.0):
    """Verdict for an event with NO assumed reference geometry (e.g. 2021): only IW/VV/coverage/valid checks; compatibility between scenes is
    judged later from (pass, relative orbit, platform). Returns (verdict, reasons)."""
    why = []
    if item.get("mode") != "IW": why.append(f"mode {item.get('mode')} != IW")
    if "VV" not in str(item.get("pols")): why.append("no VV")
    cov, val = item.get("coverage_pct"), item.get("valid_pct")
    if cov is None or cov < min_cov: why.append(f"study-area coverage {cov} % < {min_cov} %")
    if val is None or val < min_valid: why.append(f"valid pixels {val} % < {min_valid} %")
    return ("INCOMPLETE AOI COVERAGE/VALIDITY (retained, limitation recorded)" if why else "AOI COVERAGE OK (no reference geometry assumed)"), why


# ---------------------------------------------------------------- M4-A review corrections
QUERY_SCHEMA = 2
QUERY_SETTINGS = {"collection": "COPERNICUS/S1_GRD", "instrumentMode": "IW", "platform_filter": None, "valid_scale_m": 30, "angle_scale_m": 100,
                  "coverage_geodesic_area": True, "schema": QUERY_SCHEMA}


def query_fingerprint(aoi_geom, settings=None):
    """Stable fingerprint of everything that changes the cached per-scene statistics: the study-area geometry (normalised, rounded WKT) and the
    query settings. A cached window is reusable only when this matches."""
    import hashlib
    import json
    import shapely
    wkt = shapely.to_wkt(aoi_geom.normalize(), rounding_precision=9)
    cfg = dict(QUERY_SETTINGS if settings is None else settings)
    h = hashlib.sha256((wkt + "|" + json.dumps(cfg, sort_keys=True)).encode("utf-8")).hexdigest()
    return h, cfg


def cache_save(path, fingerprint, cfg, window, items):
    import json
    path.write_text(json.dumps({"fingerprint": fingerprint, "query": cfg, "window": list(window), "items": items}), encoding="utf-8")


def cache_load(path, fingerprint, window):
    """Items from a cache file ONLY if it carries the same fingerprint and window; legacy (bare list), foreign or corrupt files -> None (re-query)."""
    import json
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa
        return None
    if not isinstance(d, dict) or d.get("fingerprint") != fingerprint or list(d.get("window", [])) != list(window):
        return None
    items = d.get("items")
    return items if isinstance(items, list) and all("footprint" in i for i in items) else None


def group_query_props(date_utc, pass_, rel_orbit, platform):
    """Earth Engine property filters for ONE acquisition group (date-level mosaic). Platform is part of the key, so Sentinel-1A and
    Sentinel-1B are never combined. Platform 'SENTINEL-1A' -> platform_number 'A'."""
    return {"orbitProperties_pass": pass_, "relativeOrbitNumber_start": rel_orbit, "platform_number": str(platform)[-1].upper()}
