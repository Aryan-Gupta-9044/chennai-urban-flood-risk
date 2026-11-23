#!/usr/bin/env python
"""Module S1A (V2) - which historical events can Sentinel-1 actually support?
Queries the public ASF catalogue (no login) for scenes over the study area, then checks for a single orbit with a
pre-event baseline AND a post-event scene. Produces evidence, not flood maps. No Earth Engine needed."""
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial.study_area import bounds_wgs84
from src.flood_detection import s1_catalog as cat


ORBIT_KEYS = ["orbit", "absoluteOrbit", "absoluteOrbitNumber", "pathNumber", "relativeOrbit", "relativeOrbitNumber",
              "track", "path", "frameNumber", "flightDirection"]


def archive_previous():
    """V2.1: keep earlier outputs for comparison (copied once, never overwritten)."""
    dst = paths.OUT_TAB / "archive_before_orbit_fix"
    names = [p.name for p in paths.OUT_TAB.glob("s1_scenes_*.csv")] + ["s1_availability_summary.csv", "s1_pairing.json"]
    for n in names:
        src = paths.OUT_TAB / n
        if src.exists() and not (dst / n).exists():
            dst.mkdir(exist_ok=True)
            shutil.copy2(src, dst / n)


def diagnostics(raw):
    rows = raw[0] if raw and isinstance(raw[0], list) else raw
    d = {"records": len(rows or []), "all_keys": sorted({k for r in rows or [] for k in r}), "orbit_related": {}}
    for k in ORBIT_KEYS:
        vals = [r.get(k) for r in rows or []]
        d["orbit_related"][k] = {"present_in_records": sum(1 for r in rows or [] if k in r),
                                 "non_empty": sum(1 for v in vals if v not in (None, "", 0)),
                                 "example": next((v for v in vals if v not in (None, "")), None)}
    return d


def main():
    t0 = time.time()
    log = get_logger("S1A_availability")
    paths.ensure_dirs()
    archive_previous()
    raw_dir = paths.DATA_RAW / "s1_catalog"
    raw_dir.mkdir(parents=True, exist_ok=True)
    diag = {}
    ev_cfg = json.loads((paths.CONFIG / "s1_events.json").read_text(encoding="utf-8"))
    bbox = bounds_wgs84()
    rows, pairing, errors = [], {}, []
    for ev in ev_cfg["events"]:
        start, end = ev["pre"][0], ev["post"][1]
        try:
            def sink(raw, _id=ev["id"]):
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                (raw_dir / f"asf_{_id}_{stamp}.json").write_text(json.dumps(raw), encoding="utf-8")  # raw, never overwritten
                diag[_id] = diagnostics(raw)
            scenes = cat.search_asf(bbox, start, end, raw_sink=sink)
        except Exception as e:
            errors.append(f"{ev['id']}: {str(e)[:160]}")
            log.warning(errors[-1])
            continue
        pd.DataFrame(scenes).to_csv(paths.OUT_TAB / f"s1_scenes_{ev['id']}.csv", index=False)
        res = cat.pair_scenes(scenes, ev["pre"], ev["post"], ev["peak"])
        pairing[ev["id"]] = res
        n_full = sum(1 for s in scenes if (s["coverage_pct"] or 0) >= 95)
        rows.append({"event_id": ev["id"], "role": ev["role"], "scenes_found": len(scenes), "scenes_full_coverage": n_full,
                     "verdict": res["verdict"], "reason": res["reason"],
                     "orbit": json.dumps(res.get("orbit")), "rel_orbit_sources": ";".join(res.get("rel_orbit_sources", [])),
                     "excluded_unknown_orbit": res.get("excluded_unknown_orbit", 0), "orbit_conflicts": res.get("orbit_conflicts", 0), "pre_dates": ",".join(res.get("pre_dates", [])),
                     "post_dates": ",".join(res.get("post_dates", [])), "days_after_peak": res.get("days_after_peak", "")})
        log.info("%s: %s (%s)", ev["id"], res["verdict"], res["reason"])
    if not rows:
        status.record("S1A", status.BLOCKED, "ASF catalogue unreachable: " + " | ".join(errors[:2]),
                      requirements=["Run with internet access, or check scene availability manually at search.asf.alaska.edu "
                                    "(Sentinel-1, GRD_HD, IW) and edit windows in config/s1_events.json."], seconds=time.time() - t0)
        return
    (paths.OUT_TAB / "s1_asf_field_diagnostics.json").write_text(json.dumps(diag, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(rows).to_csv(paths.OUT_TAB / "s1_availability_summary.csv", index=False)
    (paths.OUT_TAB / "s1_pairing.json").write_text(json.dumps(pairing, indent=2), encoding="utf-8")
    ok = [r["event_id"] for r in rows if r["verdict"] == "PROCESSABLE"]
    marg = [r["event_id"] for r in rows if r["verdict"] == "MARGINAL"]
    state = status.COMPLETED if not errors else status.PARTIAL
    status.record("S1A", state, f"PROCESSABLE: {ok or 'none'}; MARGINAL: {marg or 'none'}; others not processable with one orbit. "
                  "Catalogue evidence only - scenes must also exist in the processing backend (Earth Engine).",
                  files=["outputs/tables/s1_availability_summary.csv", "outputs/tables/s1_pairing.json", "outputs/tables/s1_asf_field_diagnostics.json"],
                  datasets=[{"name": "Sentinel-1 scene catalogue (metadata)", "kind": status.REAL, "source": "ASF Search API",
                             "path": "outputs/tables/s1_availability_summary.csv"}],
                  extra={"processable": ok, "marginal": marg, "errors": errors}, seconds=time.time() - t0)


if __name__ == "__main__":
    main()
