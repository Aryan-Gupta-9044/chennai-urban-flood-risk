#!/usr/bin/env python
"""Flood-reference integration R0 (intake) + R1 (alignment) + R2 (readiness) for ONE reference file (V2.3). READ-ONLY, additive, no network, no Earth Engine/ASF/Copernicus.

Does NOT create flood labels, compute accuracy/agreement metrics or train models (R3-R5 not started). A PASS is NOT accuracy validation and does not make the file an authoritative
reference. Reference data are never reprojected, resampled, edited or overwritten. Outputs go to a NEW directory (no overwrite option); status.json is not touched.
Order of operations (hash BEFORE parse): every source is hashed first (reference, sidecar, configuration, AOI GeoJSON files, settings), then parsed/loaded, then hashed again after outputs.
Usage (PowerShell, repo root):
  .\\.venv\\Scripts\\python scripts\\reference_integration_check.py --reference path\\to\\ref.tif --meta path\\to\\ref.reference_meta.json
Sidecar template: docs/reference_meta_template.json (all UNCONFIRMED; fill ONLY from the actual file / its documented source)."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.utils import paths, config as uconfig
from src.geospatial import study_area as sa
from src.geospatial.study_area import load_study_area, master_grid
from src.flood_detection import ref_integration as RI

OUT_BASE = "outputs/flood_reference_readiness"
NAMES = ("R0_intake_findings.csv", "R1_alignment_findings.csv", "R1_temporal_offsets.csv", "R1_event_windows.csv", "R2_readiness.json", "reference_integration_report.md", "reference_integration_manifest.json")


def overlap(a, b):
    a, b = Path(a).resolve(), Path(b).resolve(); return a == b or a in b.parents or b in a.parents


PERSIST_PREFIX = "s1_2021_persistence"


def protected_dirs(root, ref):
    """Shared/protected folders: shared output folders, CHIRPS 2021 outputs, the reference's own folder, every EXISTING outputs/s1_2021_persistence* directory (any suffix: _v1_2, _v1_3, _backup, ...) and the two known names."""
    out = Path(root) / "outputs"; found = [d for d in out.glob(PERSIST_PREFIX + "*") if d.is_dir()] if out.is_dir() else []
    return [paths.OUT_REP, paths.OUT_TAB, paths.OUT_FIG, paths.OUT_MAPS, out / "chirps_2021", out / PERSIST_PREFIX, out / (PERSIST_PREFIX + "_v1_2"), Path(ref).parent, *found]


def persistence_reserved(od, root):
    """True if od is, or lies inside, ANY outputs/s1_2021_persistence* path, whether or not that directory exists yet (case-insensitive)."""
    try: rel = Path(od).resolve().relative_to((Path(root) / "outputs").resolve())
    except ValueError: return False
    return bool(rel.parts) and rel.parts[0].lower().startswith(PERSIST_PREFIX)


def flat(findings, stage): return pd.DataFrame([{"stage": stage, "code": f["code"], "level": f["level"], "message": f["message"], "evidence": json.dumps(f["evidence"], default=str, sort_keys=True)} for f in findings])


def preflight(ref, meta_p, extra):
    req = {f"reference file {Path(ref).name}": ref, "reference metadata sidecar": meta_p, "configuration s1_preprocess.json": paths.CONFIG / "s1_preprocess.json", "AOI study_area_wgs84.geojson": sa.WGS, "AOI study_area_utm44n.geojson": sa.UTM,
           "settings.json": uconfig.CONFIG / "settings.json"}; missing = [f"MISSING input: {k}: {v}" for k, v in req.items() if not Path(v).is_file()]
    if missing: return missing, None
    src = {k: Path(v) for k, v in req.items()}
    for c in RI.dataset_files(ref)[1:]: src[f"reference dataset companion file {c.name}"] = c                       # Shapefile .shx/.dbf/.prj/... or GeoTIFF sidecars
    if Path(sa.META).exists(): src["AOI study_area_meta.json (optional)"] = Path(sa.META)
    ev = paths.CONFIG / "rainfall_events.json"
    if extra and ev.exists(): src["configuration rainfall_events.json"] = ev
    return [], {"paths": src, "sha256": {k: RI.sha256_file(v) for k, v in src.items()}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); ap.add_argument("--reference", required=True); ap.add_argument("--meta", required=True); ap.add_argument("--outdir")
    ap.add_argument("--event-window", nargs=3, action="append", metavar=("NAME", "START", "END"), help="extra intended event window(s), ISO dates"); ap.add_argument("--no-config-event-window", action="store_true"); ap.add_argument("--today", help="ISO date YYYY-MM-DD (testing)"); ap.add_argument("--strict-alignment", action="store_true", help="treat raster CRS/resolution/origin mismatches as candidate-label BLOCKERS (default: explicit team-decision condition; see RI.ALIGNMENT_POLICY)")
    a = ap.parse_args(argv); root = paths.ROOT; rp = lambda x: Path(x) if Path(x).is_absolute() else root / x          # noqa: E731
    ref, mp = rp(a.reference), rp(a.meta); od = rp(a.outdir) if a.outdir else root / OUT_BASE / ref.stem
    stops, pre = preflight(ref, mp, not a.no_config_event_window)                                                    # 1. hash everything first
    if not stops:
        for sd in protected_dirs(root, ref):
            if overlap(od, sd): stops.append(f"output directory {od} overlaps protected/shared/input folder {sd}; use a dedicated new directory")
        if persistence_reserved(od, root): stops.append(f"output directory {od} lies in the reserved outputs/{PERSIST_PREFIX}* namespace (Sentinel-1 persistence outputs, existing or future); use a dedicated new directory")
        ex = [str(od / n) for n in NAMES if (od / n).exists()]
        if ex: stops.append("existing outputs would be overwritten: " + "; ".join(ex))
    if stops: print("STOP - nothing was written."); [print("  -", s) for s in stops]; return 2
    pre_find = []                                                                                                    # 2. only now parse
    try: meta = json.loads(mp.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e: meta = None; pre_find.append(RI.F("META_PARSE", RI.FAIL, "metadata sidecar is not valid JSON", error=str(e)[:200]))
    cfg = json.loads((paths.CONFIG / "s1_preprocess.json").read_text(encoding="utf-8")); scene_dates = cfg["dates"]; windows = []
    if not a.no_config_event_window and "configuration rainfall_events.json" in pre["paths"]:
        e = json.loads((paths.CONFIG / "rainfall_events.json").read_text(encoding="utf-8")).get("events", {}).get("2021_sep_nov", {}).get("event_window_proposed")
        if e: windows.append(("2021_sep_nov event window (PROPOSED, config/rainfall_events.json)", e[0], e[1]))
    windows += [tuple(w) for w in (a.event_window or [])]
    badd = [f"invalid date (strict YYYY-MM-DD required): {x}" for w in windows for x in w[1:] if RI.parse_iso_date(x) is None] + [f"invalid scene date in configuration: {x}" for x in scene_dates if RI.parse_iso_date(x) is None]
    badd += [f"--today is not a strict YYYY-MM-DD date: {a.today}"] if a.today and RI.parse_iso_date(a.today) is None else []
    if badd: print("STOP - nothing was written."); [print("  -", x) for x in badd]; return 2
    wgs, _, _ = load_study_area(); aoi = wgs.unary_union; grid = master_grid()                                       # 3. AOI/grid only after hashing
    today = date.fromisoformat(a.today) if a.today else date.today()
    r0 = RI.intake(ref, meta, aoi, today); r0["findings"] = pre_find + r0["findings"]; r0["status"] = RI.worst(r0["findings"])
    r1 = RI.alignment(ref, r0, aoi, grid, scene_dates, windows); r2 = RI.readiness(meta, r0, r1, strict_alignment=a.strict_alignment)
    od.mkdir(parents=True, exist_ok=True)
    flat(r0["findings"], "R0").to_csv(od / NAMES[0], index=False); flat(r1["findings"], "R1").to_csv(od / NAMES[1], index=False)
    r1["temporal_df"].to_csv(od / NAMES[2], index=False); r1["windows_df"].to_csv(od / NAMES[3], index=False)
    (od / NAMES[4]).write_text(json.dumps(r2, indent=1, sort_keys=True, default=str), encoding="utf-8")
    L = ["# Flood-reference integration report (R0 intake, R1 alignment, R2 readiness)", "", f"**{RI.STATEMENT}**", "", f"- Reference: `{ref}` (id: {r2['reference_id']}); metadata sidecar: `{mp}`. Run date {today}.",
         f"- R0 intake: **{r0['status']}**; R1 alignment: **{r1['status']}**; R2 primary class: **{r2['primary_class']}**.", f"- Authoritative reference: {r2['authoritative_reference']}.", f"- Alignment policy: {'STRICT (mismatches block)' if a.strict_alignment else 'DEFAULT (mismatches require an explicit team decision)'}: {RI.ALIGNMENT_POLICY}", "", "## R0 intake findings", "", "| level | code | message |", "|---|---|---|"]
    L += [f"| {f['level']} | {f['code']} | {f['message']} |" for f in r0["findings"]] + ["", "## R1 alignment findings", "", "| level | code | message |", "|---|---|---|"] + [f"| {f['level']} | {f['code']} | {f['message']} |" for f in r1["findings"]]
    L += ["", "## Temporal offsets (Sentinel-1 date minus reference observation; analyst-convention thresholds)", "", "| S1 date | offset (d) | category |", "|---|---|---|"] + [f"| {r.s1_date} | {r.offset_days} | {r.category} |" for r in r1["temporal_df"].itertuples()]
    L += ["", "## R2 readiness (independent verdicts)"]
    for k, t in (("candidate_label_comparison", "Candidate-label comparison"), ("presence_only_comparison", "Presence-only comparison"), ("qualitative_comparison", "Qualitative comparison")):
        v = r2[k]; L += ["", f"### {t}: {v['verdict']}"] + [f"- blocker: {b}" for b in v["blockers"]] + [f"- evidence {c}: {m}" for c, m in v["evidence"].items()] + [f"- alignment condition: {c}" for c in v.get("alignment_conditions", [])] + ([f"- TEAM DECISION REQUIRED: {', '.join(v['team_decision_required'])}"] if v.get("team_decision_required") else [])
    L += ["", "## Limits", "- Metadata truth (producer, licence, independence, method) is as stated in the sidecar and is NOT verified by software.", "- Footprint coverage uses bounding boxes of the data; a bounding box is not the mapped area.", "- Day thresholds (3 / 6 days) are analyst conventions.", "- No reference data were reprojected, resampled or edited; no labels or accuracy metrics were produced (R3-R5 not started)."]
    (od / NAMES[5]).write_text("\n".join(L) + "\n", encoding="utf-8")
    after = {k: RI.sha256_file(v) for k, v in pre["paths"].items()}; ok = after == pre["sha256"] and r0.get("unchanged", True)
    (od / NAMES[6]).write_text(json.dumps({"inputs_sha256_before": pre["sha256"], "inputs_sha256_after_all_outputs": after, "inputs_unchanged": ok, "r0_status": r0["status"], "r1_status": r1["status"], "primary_class": r2["primary_class"],
                                           "paths": {k: str(v) for k, v in pre["paths"].items()}, "reference_sha256_during_intake": [r0.get("sha256_before"), r0.get("sha256_after")], "reference_dataset_files": r0.get("dataset_files"), "strict_alignment": a.strict_alignment, "scene_dates": scene_dates, "event_windows": windows,
                                           "status_json_modified": False, "statement": RI.STATEMENT, "outputs": [str(od / n) for n in NAMES[:-1]]}, indent=1, sort_keys=True), encoding="utf-8")
    print(f"done. R0 {r0['status']}; R1 {r1['status']}; primary class {r2['primary_class']}; inputs unchanged: {ok}\n  report: {od / NAMES[5]}\n  {RI.STATEMENT}"); return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main() or 0)
