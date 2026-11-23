import json
import numpy as np
import geopandas as gpd
from rasterio import features
from shapely.geometry import shape


def flood_polygons(flood, grid, min_cells=4):
    """Vectorise flood==1 into polygons (EPSG:4326 GeoDataFrame, with area_km2 computed in the grid CRS)."""
    mask = flood == 1
    geoms = [shape(g) for g, v in features.shapes(flood.astype("uint8"), mask=mask, transform=grid.transform) if v == 1]
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=grid.crs)
    if len(gdf):
        gdf = gdf[gdf.area >= min_cells * grid.res ** 2].copy()
        gdf["area_km2"] = (gdf.area / 1e6).round(5)
    return gdf.to_crs(4326)


def summarise(flood, grid, inside, builtup_class=None, slope=None):
    """Descriptive statistics only (NOT accuracy)."""
    f = (flood == 1) & inside
    cell_km2 = grid.res ** 2 / 1e6
    s = {"flooded_km2": round(float(f.sum() * cell_km2), 3), "study_area_km2": round(float(inside.sum() * cell_km2), 3)}
    s["flooded_pct_of_study_area"] = round(100 * s["flooded_km2"] / s["study_area_km2"], 2) if s["study_area_km2"] else None
    if builtup_class is not None and f.any():
        s["flooded_share_in_builtup_pct"] = round(float(100 * (builtup_class[f] == 50).mean()), 1)
        s["builtup_share_of_study_area_pct"] = round(float(100 * (builtup_class[inside] == 50).mean()), 1)
    if slope is not None and f.any():
        s["flooded_mean_slope_deg"] = round(float(np.mean(slope[f])), 2)
    return s
