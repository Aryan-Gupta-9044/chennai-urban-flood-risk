"""Module status registry -> outputs/reports/status.json (read by the report and dashboard)."""
import json
import os
from datetime import datetime
from .paths import OUT_REP, ensure_dirs

COMPLETED = "COMPLETED"
PARTIAL = "PARTIALLY COMPLETED"
BLOCKED = "BLOCKED"
NOT_STARTED = "NOT STARTED"

# Data provenance labels used everywhere
REAL = "REAL"                    # downloaded from the named public source
USER = "USER-SUPPLIED"           # placed by the user in data/external
PROVISIONAL = "PROVISIONAL"      # real but not yet verified against an official source
SAMPLE = "SAMPLE"                # small real subset for demonstration
SIMULATED = "SIMULATED"          # synthetic (never produced by the pipeline itself)
DERIVED = "DERIVED"              # computed from the inputs above

MODULES = [
    ("0", "Environment check"),
    ("A1", "Chennai study-area boundary"),
    ("A2", "Ward boundaries"),
    ("B", "DEM: elevation and slope"),
    ("HYD", "Hydrological terrain analysis (V2.3, terrain-derived, unverified)"),
    ("C", "Rainfall (CHIRPS sample)"),
    ("IMD", "IMD 0.25 deg rainfall: acquisition + native conversion (V2.3 demo)"),
    ("CH3", "CHIRPS v3 DAILY_SAT: coverage probe (V2.3)"),
    ("CH3A", "CHIRPS v3 DAILY_SAT: controlled acquisition of the 153-day window (V2.3)"),
    ("CH3P", "CHIRPS v3 DAILY_SAT: prepare workflow-ready daily rasters (V2.3)"),
    ("CH3_2021", "CHIRPS v3 DAILY_SAT 2021 context window: coverage probe (V2.3, isolated)"),
    ("CH3A_2021", "CHIRPS v3 DAILY_SAT 2021 context window: controlled acquisition of the 115-day window (V2.3, isolated)"),
    ("CH3P_2021", "CHIRPS v3 DAILY_SAT 2021 context window: prepare workflow-ready daily rasters (V2.3, isolated)"),
    ("CMP", "CHIRPS vs IMD side-by-side comparison (V2.3, not validation)"),
    ("C2", "Rainfall event workflow (V2.3, source-agnostic, native grid)"),
    ("C2_2021", "Rainfall event workflow, 2021 event (V2.3, isolated status id)"),
    ("D", "Land cover (ESA WorldCover)"),
    ("E", "Data integration and feature table"),
    ("F", "Flood inventory foundation"),
    ("S1A", "Sentinel-1 availability and orbit pairing (V2)"),
    ("S1G", "Sentinel-1 scene check in Earth Engine (V2.1)"),
    ("S1W", "Sentinel-1 window scan for better dates (V2.3)"),
    ("S1I", "Sentinel-1 acquisition inventory + baseline candidates (V2.3)"),
    ("S1DC", "Sentinel-1 date-level multi-slice coverage verification (V2.3)"),
    ("S1PP", "Sentinel-1 2021 date-level preprocessing (V2.3, M4C)"),
    ("S1PD", "Sentinel-1 2021 product QA diagnostics (V2.3, M4C review)"),
    ("REF", "Independent-reference readiness matrix (V2.3)"),
    ("S1B", "Sentinel-1 flood extent (V2.2, scene-pinned SAR proxy, unvalidated)"),
    ("G", "Random Forest pipeline"),
    ("H", "Dashboard"),
]
STATUS_FILE = OUT_REP / "status.json"


def load():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"modules": {}}


def record(module_id, state, message="", files=(), datasets=(), requirements=(), extra=None, seconds=None):
    ensure_dirs()
    data = load()
    title = dict(MODULES).get(module_id, module_id)
    entry = {
        "id": module_id, "title": title, "state": state, "message": message,
        "files": [str(f) for f in files], "datasets": list(datasets),
        "requirements": list(requirements), "extra": extra or {},
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    if seconds is not None:
        entry["seconds"] = round(seconds, 1)
    data.setdefault("modules", {})[module_id] = entry
    tmp = str(STATUS_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATUS_FILE)
    return entry
