#!/usr/bin/env python
"""Run every module in order, each in its own subprocess so one failure never stops the rest."""
import argparse
import subprocess
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils import status as S, paths
from src.utils.logging_setup import get_logger

STEPS = [  # (module id, script, timeout seconds)
    ("0", "check_environment.py", 120),
    ("A1", "download_boundaries.py", 300),
    ("A2", "process_wards.py", 300),
    ("B", "process_dem.py", 900),
    ("HYD", "process_hydrology.py", 900),
    ("C", "process_rainfall.py", 900),
    ("D", "process_landcover.py", 900),
    ("E", "build_features.py", 600),
    ("F", "create_inventory.py", 900),
    ("S1A", "s1_availability.py", 400),
    ("S1B", "s1b_flood_extent.py", 3600),
    ("G", "train_random_forest.py", 900),
    ("H", "verify_dashboard.py", 300),
    ("R", "make_report.py", 120),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated module ids, e.g. B,C")
    ap.add_argument("--skip", default="", help="comma-separated module ids to skip")
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    skip = {x.strip() for x in a.skip.split(",") if x.strip()}
    paths.ensure_dirs()
    log = get_logger("pipeline_runner")
    t_all = time.time()
    steps = [s for s in STEPS if (not only or s[0] in only or s[0] == "R") and s[0] not in skip]
    # Module G (legacy RF v0) trains on SAR proxy labels and is RETIRED (docs/final/RF_V0_RETIREMENT.md).
    # It runs only when explicitly requested with CHENNAI_ALLOW_LEGACY_RF=1; its outputs are never a flood prediction.
    import os
    if os.environ.get("CHENNAI_ALLOW_LEGACY_RF") != "1" and any(s[0] == "G" for s in steps):
        steps = [s for s in steps if s[0] != "G"]
        log.warning("Module G (legacy RF v0) skipped: retired. Set CHENNAI_ALLOW_LEGACY_RF=1 to run it for traceability only.")
    log.info("=== Chennai flood-risk pipeline: %d steps ===", len(steps))
    for i, (mid, script, to) in enumerate(steps, 1):
        title = dict(S.MODULES).get(mid, "Report")
        log.info("[%d/%d] %s %s  (%s)", i, len(steps), mid, title, script)
        t0 = time.time()
        before = S.load().get("modules", {}).get(mid, {}).get("updated")
        try:
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=str(ROOT), timeout=to,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = (r.stdout or "") + (r.stderr or "")
            (paths.LOGS / f"{mid}_{Path(script).stem}.out.txt").write_text(out, encoding="utf-8")
            crashed = r.returncode != 0
            tail = "\n".join(out.strip().splitlines()[-12:])
        except subprocess.TimeoutExpired:
            crashed, tail = True, f"timed out after {to}s"
        after = S.load().get("modules", {}).get(mid, {}).get("updated")
        if mid != "R" and (crashed and (after == before or after is None)):
            S.record(mid, S.BLOCKED, f"Script crashed (see logs/{mid}_{Path(script).stem}.out.txt): {tail[-300:]}",
                     seconds=time.time() - t0)
            log.error("   -> crashed. Last lines:\n%s", tail)
        elif crashed:
            log.warning("   -> exited with an error after recording status; last lines:\n%s", tail)
        m = S.load().get("modules", {}).get(mid, {})
        if mid != "R":
            log.info("   -> %s (%.1fs): %s", m.get("state", "NOT STARTED"), time.time() - t0, (m.get("message", "") or "")[:200])
    mods = S.load().get("modules", {})
    log.info("")
    log.info("=============== COMPLETION SUMMARY ===============")
    for mid, title in S.MODULES:
        log.info("  %-3s %-38s %s", mid, title, mods.get(mid, {}).get("state", "NOT STARTED"))
    log.info("Total time: %.0fs", time.time() - t_all)
    log.info("Report:  outputs/reports/implementation_summary.html")
    log.info("Log:     logs/pipeline.log")
    log.info("Dashboard:  .venv\\Scripts\\streamlit run dashboard\\app.py")


if __name__ == "__main__":
    main()
