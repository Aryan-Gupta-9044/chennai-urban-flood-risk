"""Verification gate for the S1B flood-extent step: processing starts ONLY if every pinned scene was verified in Earth Engine.
Input rows come from outputs/tables/s1_gee_availability_<event>.csv (written by scripts/s1_gee_check.py after a LIVE Earth Engine query)."""
from .s1_orbits import parse_scene_name, relative_from_absolute


def _vv(pol):
    return "VV" in str(pol).upper()


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def verify_scenes(event_cfg, rows, min_pre=3):
    """Returns {'ok': bool, 'problems': [str], 'scenes': [dict]}. Every problem blocks processing."""
    ids = event_cfg.get("scene_ids") or {}
    pre, post = list(ids.get("pre", [])), list(ids.get("post", []))
    orb = event_cfg.get("orbit") or {}
    problems, table = [], []
    if not orb.get("direction") or not orb.get("rel_orbit"):
        problems.append("event config has no 'orbit' (direction + rel_orbit)")
    if len(pre) < min_pre:
        problems.append(f"only {len(pre)} pre-event scene IDs configured (need >= {min_pre})")
    if len(post) != 1:
        problems.append(f"exactly one post-event scene ID is required (found {len(post)})")
    allids = pre + post
    if len(set(allids)) != len(allids):
        problems.append("duplicate scene IDs in configuration")
    by_scene = {}
    for r in rows:
        by_scene.setdefault(r.get("scene"), []).append(r)
    dates = {}
    for role, lst in (("pre", pre), ("post", post)):
        for sid in lst:
            info = parse_scene_name(sid)
            item = {"role": role, "scene": sid, "checks": {}}
            if not info or info["clean_name"] != sid:
                problems.append(f"{sid}: not a valid Sentinel-1 product name")
                table.append(item)
                continue
            d = info["start_date"]
            iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            dates[sid] = iso
            rr = by_scene.get(sid, [])
            if len(rr) != 1:
                problems.append(f"{sid}: {'not present in' if not rr else 'duplicated in'} the Earth Engine verification table")
                item["checks"]["row_present"] = False
                table.append(item)
                continue
            r = rr[0]
            exp_rel = relative_from_absolute(info["platform_code"], info["abs_orbit"])[0]
            chk = {
                "found": str(r.get("status")).strip().upper() == "FOUND",
                "exact_system_index": str(r.get("match_method")).startswith("exact") and str(r.get("gee_id")) == sid,
                "date": str(r.get("date")) == iso,
                "direction": str(r.get("catalogue_direction")).upper() == str(orb.get("direction")).upper()
                             and str(r.get("gee_pass")).upper() == str(orb.get("direction")).upper(),
                "relative_orbit": _int(r.get("gee_rel_orbit")) == _int(orb.get("rel_orbit")),
                "formula_orbit_consistent": exp_rel == _int(orb.get("rel_orbit")),
                "polarisation_VV": _vv(r.get("gee_polarisation")),
            }
            for k, v in chk.items():
                if not v:
                    problems.append(f"{sid}: check '{k}' failed")
            item["checks"] = chk
            item.update(date=iso, abs_orbit=info["abs_orbit"], platform=info["platform_code"],
                        gee_rel_orbit=_int(r.get("gee_rel_orbit")), gee_pass=r.get("gee_pass"), polarisation=r.get("gee_polarisation"))
            table.append(item)
    if pre and post and all(s in dates for s in pre + post):
        if max(dates[s] for s in pre) >= dates[post[0]]:
            problems.append("a pre-event scene is not earlier than the post-event scene")
    return {"ok": not problems, "problems": problems, "scenes": table}
