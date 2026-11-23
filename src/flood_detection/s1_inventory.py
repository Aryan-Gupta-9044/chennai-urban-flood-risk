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
