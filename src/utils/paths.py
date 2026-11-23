"""Project paths (all relative to the project root, never hard-coded)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
DATA_RAW = ROOT / "data" / "raw"
DATA_PROC = ROOT / "data" / "processed"
DATA_EXT = ROOT / "data" / "external"
OUT_MAPS = ROOT / "outputs" / "maps"
OUT_FIG = ROOT / "outputs" / "figures"
OUT_REP = ROOT / "outputs" / "reports"
OUT_TAB = ROOT / "outputs" / "tables"
OUT_MODELS = ROOT / "outputs" / "models"
LOGS = ROOT / "logs"
DOCS = ROOT / "docs"

ALL_DIRS = [DATA_RAW, DATA_PROC, DATA_EXT, OUT_MAPS, OUT_FIG, OUT_REP, OUT_TAB, OUT_MODELS, LOGS, DOCS,
            DATA_EXT / "boundary", DATA_EXT / "wards", DATA_EXT / "dem", DATA_EXT / "landcover",
            DATA_EXT / "flood_labels", DATA_EXT / "sentinel1"]


def ensure_dirs():
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def rel(p):
    """Path relative to project root, with forward slashes (for reports)."""
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def external_kind():
    """Files placed by the user in data/external are USER-SUPPLIED.
    A marker file (used only by developer tests) flips this to SIMULATED."""
    return "SIMULATED" if (DATA_EXT / "SIMULATED_FIXTURE.txt").exists() else "USER-SUPPLIED"
