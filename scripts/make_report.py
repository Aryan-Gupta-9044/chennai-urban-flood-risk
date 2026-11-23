#!/usr/bin/env python
"""Build outputs/reports/implementation_summary.html, dataset_inventory.csv and module_summary.csv."""
import html
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.utils import status as S, paths
from src.utils.logging_setup import get_logger

COL = {"COMPLETED": "#1a7f37", "PARTIALLY COMPLETED": "#b7791f", "BLOCKED": "#c0392b", "NOT STARTED": "#777"}
KCOL = {"REAL": "#1a7f37", "SAMPLE": "#2b7bba", "USER-SUPPLIED": "#2b7bba", "PROVISIONAL": "#b7791f", "PROVISIONAL-WARD-UNION": "#b7791f",
        "SIMULATED": "#8e44ad", "PLACEHOLDER": "#c0392b"}


def next_task(mods):
    st = lambda k: mods.get(k, {}).get("state", S.NOT_STARTED)
    if st("0") == S.BLOCKED:
        return "Fix the environment: re-run run.ps1 and read the pip error in logs/pipeline.log."
    if st("A1") != S.COMPLETED and mods.get("A1", {}).get("extra", {}).get("kind") == "PLACEHOLDER":
        return "Re-run with internet access so the real Chennai boundary can be fetched (currently a rough placeholder rectangle)."
    if st("A2") == S.BLOCKED:
        return "Obtain ward boundaries: put a ward GeoJSON/Shapefile in data/external/wards/ and re-run."
    if st("B") == S.BLOCKED or st("D") == S.BLOCKED:
        return "Obtain DEM / land cover (internet access, or place GeoTIFFs in data/external/)."
    if st("F") != S.COMPLETED and not mods.get("F", {}).get("extra", {}).get("events_with_extent"):
        return ("Task: Sentinel-1 flood extent for ONE event (2023 Michaung). Do the one-time Earth Engine authentication, "
                "re-run, then inspect data/processed/flood_extent_2023_dec_*.tif against reference information.")
    if st("G") == S.BLOCKED:
        return "Provide verified labels so the Random Forest can run."
    return "Next: XGBoost + SHAP, then OSM drainage/roads and flow accumulation/TWI features."


def main():
    log = get_logger("report")
    paths.ensure_dirs()
    data = S.load()
    mods = data.get("modules", {})
    order = [m for m, _ in S.MODULES]
    rows = []
    for k in order:
        m = mods.get(k)
        rows.append({"module": k, "title": dict(S.MODULES)[k], "state": (m or {}).get("state", S.NOT_STARTED),
                     "seconds": (m or {}).get("seconds", ""), "message": (m or {}).get("message", "Not run.")})
    pd.DataFrame(rows).to_csv(paths.OUT_TAB / "module_summary.csv", index=False)

    ds_rows = []
    for k in order:
        for d in (mods.get(k) or {}).get("datasets", []):
            p = d.get("path", "")
            ds_rows.append({"module": k, "dataset": d.get("name"), "kind": d.get("kind"), "source": d.get("source"),
                            "path": p, "exists": (paths.ROOT / p).exists() if p else False})
    inv = pd.DataFrame(ds_rows, columns=["module", "dataset", "kind", "source", "path", "exists"])
    inv.to_csv(paths.OUT_TAB / "dataset_inventory.csv", index=False)

    gen = []
    for base in (paths.OUT_MAPS, paths.OUT_FIG, paths.OUT_REP, paths.OUT_TAB, paths.DATA_PROC, paths.OUT_MODELS):
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name != ".gitkeep" and not p.name.endswith(".tmp"):
                gen.append((paths.rel(p), p.stat().st_size))
    esc = html.escape
    out = ["<!doctype html><html><head><meta charset='utf-8'><title>Implementation summary</title><style>"
           "body{font:14px/1.5 Segoe UI,Arial,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222}"
           "table{border-collapse:collapse;width:100%;margin:8px 0 24px}td,th{border:1px solid #ddd;padding:6px 8px;"
           "text-align:left;vertical-align:top}th{background:#f3f3f3}.b{color:#fff;padding:2px 8px;border-radius:4px;"
           "white-space:nowrap;font-size:12px}code{background:#f3f3f3;padding:1px 4px}h2{margin-top:28px}</style></head><body>",
           "<h1>Chennai Flood Risk - implementation summary</h1>",
           f"<p>Generated {datetime.now():%Y-%m-%d %H:%M:%S}. Project B794 foundation package. "
           "Data kinds: <span class='b' style='background:#1a7f37'>REAL</span> "
           "<span class='b' style='background:#2b7bba'>SAMPLE / USER-SUPPLIED</span> "
           "<span class='b' style='background:#b7791f'>PROVISIONAL</span> "
           "<span class='b' style='background:#8e44ad'>SIMULATED</span> (the pipeline itself never creates simulated data).</p>",
           "<h2>Next recommended implementation task</h2><p><b>" + esc(next_task(mods)) + "</b></p>",
           "<h2>Modules</h2><table><tr><th>ID</th><th>Module</th><th>State</th><th>Seconds</th><th>Details</th></tr>"]
    for r in rows:
        out.append(f"<tr><td>{r['module']}</td><td>{esc(r['title'])}</td><td><span class='b' style='background:{COL[r['state']]}'>"
                   f"{r['state']}</span></td><td>{r['seconds']}</td><td>{esc(str(r['message']))}</td></tr>")
    out.append("</table>")
    for title, pred in (("Modules completed", lambda s: s == S.COMPLETED), ("Modules partially completed", lambda s: s == S.PARTIAL),
                        ("Modules blocked / failed", lambda s: s == S.BLOCKED), ("Modules not started", lambda s: s == S.NOT_STARTED)):
        names = [f"{r['module']} {r['title']}" for r in rows if pred(r["state"])]
        out.append(f"<h2>{title} ({len(names)})</h2><p>{esc('; '.join(names)) or 'none'}</p>")
    out.append("<h2>Datasets acquired</h2><table><tr><th>Module</th><th>Dataset</th><th>Kind</th><th>Source</th><th>Path</th><th>On disk</th></tr>")
    for _, r in inv.iterrows():
        k = str(r["kind"]).split(" ")[0]
        out.append(f"<tr><td>{r['module']}</td><td>{esc(str(r['dataset']))}</td><td><span class='b' style='background:{KCOL.get(k, '#555')}'>"
                   f"{esc(str(r['kind']))}</span></td><td>{esc(str(r['source']))}</td><td><code>{esc(str(r['path']))}</code></td><td>{r['exists']}</td></tr>")
    out.append("</table><h2>Remaining requirements</h2><ul>")
    seen = set()
    for k in order:
        m = mods.get(k) or {}
        if m.get("state") != S.COMPLETED or m.get("requirements"):
            for q in m.get("requirements", []):
                if q not in seen:
                    seen.add(q)
                    out.append(f"<li><b>{k}</b>: {esc(q)}</li>")
    out.append("</ul>")
    out.append(f"<h2>Files generated ({len(gen)})</h2><table><tr><th>File</th><th>KB</th></tr>")
    for f, s in gen:
        out.append(f"<tr><td><code>{esc(f)}</code></td><td>{s / 1024:.1f}</td></tr>")
    out.append("</table><h2>Logs</h2><p><code>logs/pipeline.log</code> (everything) and one log per module in <code>logs/</code>.</p></body></html>")
    (paths.OUT_REP / "implementation_summary.html").write_text("\n".join(out), encoding="utf-8")
    log.info("report written: outputs/reports/implementation_summary.html")


if __name__ == "__main__":
    main()
