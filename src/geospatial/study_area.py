"""Load the processed study area written by scripts/download_boundaries.py."""
import json
import geopandas as gpd
from ..utils.paths import DATA_PROC
from ..utils.config import load_settings

WGS = DATA_PROC / "study_area_wgs84.geojson"
UTM = DATA_PROC / "study_area_utm44n.geojson"
META = DATA_PROC / "study_area_meta.json"


def load_study_area():
    if not (WGS.exists() and UTM.exists()):
        raise FileNotFoundError("Study area not found. Run scripts/download_boundaries.py first.")
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    return gpd.read_file(WGS), gpd.read_file(UTM), meta


def bounds_wgs84(pad=0.0):
    g, _, _ = load_study_area()
    minx, miny, maxx, maxy = g.total_bounds
    return (minx - pad, miny - pad, maxx + pad, maxy + pad)


def master_grid():
    from .grid import make_master_grid
    _, u, _ = load_study_area()
    s = load_settings()
    return make_master_grid(u.total_bounds, s["grid_resolution_m"], s["analysis_epsg"])
