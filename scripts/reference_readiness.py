#!/usr/bin/env python
"""Module REF (V2.3) - write the independent-reference data-readiness matrix from config/reference_datasets.json.
No download, no network. Outputs: outputs/tables/reference_readiness.csv, outputs/reports/reference_readiness.md"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.utils import paths, status
from src.flood_detection.ref_readiness import status_of


def main():
    paths.ensure_dirs()
    cfg = json.loads((paths.CONFIG / "reference_datasets.json").read_text(encoding="utf-8"))
    rows = [{**d, "readiness": status_of(d)} for d in cfg["datasets"]]
    pd.DataFrame(rows).to_csv(paths.OUT_TAB / "reference_readiness.csv", index=False)
    L = ["# Independent-reference data-readiness matrix", "", "Nothing below has been downloaded or verified by SHIVE. UNCONFIRMED = not established.", "",
         "| dataset | obs. date | sensor/source | independent of S1 | format | CRS | extent | access | licence | readiness |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['name']} | {r['obs_date']} | {r['sensor_family']} | {r['independent_of_s1']} | {r['format']} | {r['crs']} | {r['extent']} | {r['access']} | {r['licence']} | {r['readiness']} |")
    L += ["", "## Technical requirements before any dataset is used for comparison", ""] + [f"- {x}" for x in cfg["ingest_requirements"]]
    L += ["", "Comparison against any reference yields AGREEMENT metrics only; it is not accuracy unless the reference quality is established."]
    (paths.OUT_REP / "reference_readiness.md").write_text("\n".join(L), encoding="utf-8")
    status.record("REF", status.PARTIAL, f"{len(rows)} candidate references registered; 0 obtained.", files=["outputs/reports/reference_readiness.md"])
    print("\n".join(L))


if __name__ == "__main__":
    main()
