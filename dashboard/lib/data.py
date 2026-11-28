"""Cached geodata loaders (read-only)."""
from __future__ import annotations

import streamlit as st

from . import registry as R


@st.cache_data(show_spinner=False)
def _read_gpkg(path):
    import geopandas as gpd
    return gpd.read_file(path)


def gpkg(key):
    return _read_gpkg(str(R.P[key])) if R.exists(key) else None


def wards():
    """Ward polygons (EPSG:32644) with the DEP2 integrated attributes."""
    return gpkg("wards_gpkg")


def aoi():
    return _read_gpkg(str(R.P["aoi_wgs84"])) if R.exists("aoi_wgs84") else None


def ward_table():
    """Ward polygons joined to the ML-EXP-1 feature matrix and clusters, if present."""
    W = wards()
    if W is None:
        return None
    f = R.csv("mlx_features")
    if f is not None:
        keep = [c for c in f.columns if c not in W.columns or c == "ward_no"]
        W = W.merge(f[keep], on="ward_no", how="left")
    c = R.csv("mlx_clusters")
    if c is not None:
        W = W.merge(c, on="ward_no", how="left")
    return W
