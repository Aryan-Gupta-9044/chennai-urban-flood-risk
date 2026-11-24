#!/usr/bin/env python
"""Read-only SHA-256 preservation check of the 2015 CHIRPS v3 evidence (raw/daily rasters, probe files, manifests, source metadata, reports, tables, figure).
  --snapshot FILE : record the hashes of every existing 2015 file  (run BEFORE any 2021 command)
  --verify FILE   : recompute and compare with that snapshot; exit 1 if any file was modified or deleted (new files are only listed)
The snapshot file is written OUTSIDE the protected locations by default (the path you pass). Nothing is modified, moved or deleted."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.geospatial import chirps_runpaths as RP


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot"); g.add_argument("--verify"); ap.add_argument("--root", default=None, help="project root (default: this repository)")
    a = ap.parse_args()
    if a.snapshot:
        out = Path(a.snapshot)
        snap = RP.snapshot(a.root)
        RP.save_snapshot(out, snap); print(f"snapshot of {len(snap)} 2015 CHIRPS files written to {out}")
        if not snap: print("NOTE: no 2015 CHIRPS files were found under this root; nothing is protected here.")
        return 0
    before = RP.load_snapshot(a.verify); res = RP.compare(before, RP.snapshot(a.root))
    print(f"2015 CHIRPS files in snapshot: {len(before)}; unchanged: {res['unchanged']}; modified: {len(res['modified'])}; deleted: {len(res['deleted'])}; new (informational): {len(res['added'])}")
    for k in ("modified", "deleted"):
        for x in res[k]: print(f"  {k.upper()}: {x}")
    for x in res["added"][:20]: print(f"  new: {x}")
    ok = not res["modified"] and not res["deleted"]; print("RESULT:", "PRESERVED (all snapshot files byte-identical)" if ok else "VIOLATION - 2015 evidence changed"); return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
