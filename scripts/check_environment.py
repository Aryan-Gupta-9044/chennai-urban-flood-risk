#!/usr/bin/env python
"""Module 0 - verify Python and required packages."""
import importlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils import status, paths
from src.utils.logging_setup import get_logger

REQUIRED = [("numpy", "numpy"), ("pandas", "pandas"), ("geopandas", "geopandas"), ("shapely", "shapely"),
            ("pyproj", "pyproj"), ("rasterio", "rasterio"), ("matplotlib", "matplotlib"), ("folium", "folium"),
            ("osmnx", "osmnx"), ("requests", "requests"), ("sklearn", "scikit-learn"),
            ("joblib", "joblib"), ("streamlit", "streamlit")]
OPTIONAL = [("ee", "earthengine-api (needed only for Sentinel-1 via Google Earth Engine)")]


def main():
    log = get_logger("environment")
    paths.ensure_dirs()
    log.info("Python %s on %s", sys.version.split()[0], sys.platform)
    problems, rows = [], []
    if not ((3, 10) <= sys.version_info[:2] <= (3, 13)):
        log.warning("Python %d.%d is outside the tested range 3.10-3.13; wheels for geo packages may be missing.",
                    *sys.version_info[:2])
    for mod, label in REQUIRED:
        try:
            m = importlib.import_module(mod)
            rows.append(f"OK    {label} {getattr(m, '__version__', '')}")
        except Exception as e:
            rows.append(f"FAIL  {label}: {e}")
            problems.append(label)
    for mod, label in OPTIONAL:
        try:
            importlib.import_module(mod)
            rows.append(f"OK    {label}")
        except Exception:
            rows.append(f"MISS  {label}")
    for r in rows:
        log.info(r)
    if problems:
        status.record("0", status.BLOCKED, "Missing required packages: " + ", ".join(problems),
                      requirements=["pip install -r requirements.txt"])
        sys.exit(1)
    status.record("0", status.COMPLETED, f"Python {sys.version.split()[0]}; all required packages import.",
                  extra={"packages": rows})


if __name__ == "__main__":
    main()
