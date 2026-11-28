"""Exposure: what people and assets are present (ward level and feature level).

Exposure is NOT hazard and NOT vulnerability. Quantities are raw counts/areas/lengths; normalised
scores are kept in separate columns (suffix `_score`). Nothing here says that an asset flooded.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import ANALYSIS_CRS, LOG
from .layers import read_gz_geojson

FACILITY_LAYERS = {
    # name: (TNGIS file, category, attribute holding the name / type)
    "health_facility_public": ("health_facilities.geojson.gz", "health", "facility_type"),
    "school": ("schools.geojson.gz", "education", "category"),
    "gcc_school": ("gcc_schools.geojson.gz", "education", None),
    "police_station": ("police_stations.geojson.gz", "emergency", None),
    "evacuation_shelter": ("evacuation_shelters.geojson.gz", "emergency", None),
    "gcc_ward_office": ("gcc_ward_office.geojson.gz", "administrative", None),
    "gcc_zone_office": ("gcc_zone_office.geojson.gz", "administrative", None),
    "gcc_community_hall": ("gcc_community_hall.geojson.gz", "public_service", "category"),
}


def facility_inventory(src, wards):
    """Critical-facility inventory from TNGIS (government GIS) + CDMP relief centres placed by the gazetteer."""
    import geopandas as gpd
    parts = []
    for key, (fn, cat, attr) in FACILITY_LAYERS.items():
        g = read_gz_geojson(src.tngis / fn).to_crs(ANALYSIS_CRS)
        if len(g) == 0:
            continue
        g["geometry"] = g.geometry.representative_point()
        g["facility_class"] = key
        g["facility_group"] = cat
        g["source_subtype"] = g[attr].astype(str) if attr and attr in g else None
        nm = next((c for c in ("facility_name", "name", "location", "street_name", "address") if c in g), None)
        g["facility_name"] = g[nm].astype(str) if nm else None
        g["source"] = f"TNGIS WFS {fn.replace('.geojson.gz', '')} (via reclaimchennai raw/tngis, commit 56c3a6a)"
        parts.append(g[["facility_class", "facility_group", "source_subtype", "facility_name", "source", "geometry"]])
    rel = gpd.read_file(src.relief_layer).to_crs(ANALYSIS_CRS)
    if len(rel):
        rel = rel[rel.geometry.notna() & ~rel.geometry.is_empty].copy()
        rel["geometry"] = rel.geometry.representative_point()
        rel["facility_class"] = "relief_centre_cdmp"
        rel["facility_group"] = "emergency"
        rel["source_subtype"] = rel.get("prec", pd.Series(index=rel.index, dtype=str)).astype(str)
        rel["facility_name"] = rel.get("name", pd.Series(index=rel.index, dtype=str)).astype(str)
        rel["source"] = "GCC CDMP 2026 relief centres, placed by reclaimchennai gazetteer (precision in source_subtype)"
        parts.append(rel[["facility_class", "facility_group", "source_subtype", "facility_name", "source", "geometry"]])
    fac = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=ANALYSIS_CRS)
    fac = gpd.sjoin(fac, wards[["ward_no", "geometry"]], how="left", predicate="within").drop(columns="index_right")
    fac["dup_key"] = fac.facility_class + "|" + fac.geometry.x.round(0).astype(str) + "|" + fac.geometry.y.round(0).astype(str)
    fac["duplicate_location_same_class"] = fac.dup_key.duplicated(keep="first")
    fac = fac.drop(columns="dup_key").reset_index(drop=True)
    fac.insert(0, "facility_id", [f"FAC-{i:05d}" for i in range(len(fac))])
    LOG.info("facility inventory: %d features (%d outside GCC wards)", len(fac), int(fac.ward_no.isna().sum()))
    return fac


def roads(src, wards):
    """Road quantities: TNGIS GCC road-surface polygons (area) and OSM NAMED highway lines (length)."""
    import geopandas as gpd
    rp = read_gz_geojson(src.tngis / "gcc_roads.geojson.gz").to_crs(ANALYSIS_CRS)
    rp["geometry"] = rp.buffer(0)
    rp = rp[~rp.is_empty]
    ol = read_gz_geojson(src.osm / "lines.geojson.gz").to_crs(ANALYSIS_CRS)
    ol = ol[ol.highway.notna()]
    w = wards[["ward_no", "geometry"]]
    ra = gpd.overlay(rp[["geometry"]], w, how="intersection", keep_geom_type=True)
    ra["a"] = ra.area
    ln = gpd.overlay(ol[["highway", "geometry"]], w, how="intersection", keep_geom_type=True)
    ln["l"] = ln.length
    major = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
    out = pd.DataFrame({"ward_no": wards.ward_no})
    out = out.merge(ra.groupby("ward_no").a.sum().rename("road_surface_area_m2"), on="ward_no", how="left")
    out = out.merge(ln.groupby("ward_no").l.sum().rename("osm_named_road_length_m"), on="ward_no", how="left")
    out = out.merge(ln[ln.highway.isin(major)].groupby("ward_no").l.sum().rename("osm_named_major_road_length_m"), on="ward_no", how="left")
    out = out.fillna({"road_surface_area_m2": 0.0, "osm_named_road_length_m": 0.0, "osm_named_major_road_length_m": 0.0})
    LOG.info("roads: %d TNGIS road polygons, %d OSM named highway lines", len(rp), len(ol))
    return out, rp, ol


def worldpop_zonal(src, wards):
    """Zonal sum of the WorldPop 2020 constrained 100 m layer (as clipped by km658). Coverage per ward is reported;
    a ward is given a total only where >= 95% of its area has valid WorldPop cells (no extrapolation)."""
    import rasterio
    from rasterio.features import rasterize
    with rasterio.open(src.worldpop) as d:
        a = d.read(1).astype("float64")
        nd = d.nodata
        tr, shp, crs = d.transform, d.shape, d.crs
    valid = np.isfinite(a) & (a != nd)
    ids = rasterize(((g, int(w)) for g, w in zip(wards.to_crs(crs).geometry, wards.ward_no)), out_shape=shp, transform=tr, fill=0, dtype="int32")
    cell = abs(tr.a * tr.e)
    rows = []
    for w in wards.ward_no:
        m = ids == w
        n = int(m.sum())
        nv = int((m & valid).sum())
        rows.append({"ward_no": int(w), "wp_cells_in_ward": n, "wp_valid_cells": nv,
                     "wp_valid_share": nv / n if n else 0.0, "wp_pop_sum_valid_cells": float(a[m & valid].sum()) if nv else np.nan})
    z = pd.DataFrame(rows)
    z["wp_population_2020"] = np.where(z.wp_valid_share >= 0.95, z.wp_pop_sum_valid_cells, np.nan)
    z["wp_coverage_flag"] = np.where(z.wp_cells_in_ward == 0, "NO_COVERAGE", np.where(z.wp_valid_share >= 0.95, "COMPLETE", "PARTIAL_NOT_TOTALLED"))
    info = {"raster_crs": str(crs), "cell_m": [tr.a, -tr.e], "valid_cells": int(valid.sum()), "total_population_valid_cells": float(a[valid].sum()),
            "cell_area_m2": cell, "wards_complete": int((z.wp_coverage_flag == "COMPLETE").sum())}
    LOG.info("WorldPop zonal: %d wards with complete coverage", info["wards_complete"])
    return z, info


def near_reported(features, reports, radius_m: float):
    """Boolean: feature within `radius_m` (plus each report's own positional uncertainty) of a placed reported location."""
    if len(reports) == 0:
        return np.zeros(len(features), bool)
    buf = reports.geometry.buffer(radius_m + reports.position_uncertainty_m.fillna(0).values)
    zone = buf.union_all() if hasattr(buf, "union_all") else buf.unary_union
    return features.geometry.intersects(zone).values


def exposure_table(wards, pop, roads_t, wp, fac, reports_by_year: dict, radius_m=250.0):
    w = wards.drop(columns="geometry").copy()
    t = w.merge(pop[["ward_no", "households", "population"]].rename(columns={"population": "population_cdmp", "households": "households_cdmp"}), on="ward_no", how="left")
    t = t.merge(wp[["ward_no", "wp_population_2020", "wp_valid_share", "wp_coverage_flag"]], on="ward_no", how="left")
    t = t.merge(roads_t, on="ward_no", how="left")
    t["population_density_cdmp_per_km2"] = t.population_cdmp / t.area_km2
    t["road_surface_share"] = t.road_surface_area_m2 / (t.area_km2 * 1e6)
    t["osm_named_road_density_km_per_km2"] = t.osm_named_road_length_m / 1000 / t.area_km2
    cnt = fac[~fac.duplicate_location_same_class].groupby(["ward_no", "facility_group"]).size().unstack(fill_value=0)
    cnt.columns = [f"n_{c}_facilities" for c in cnt.columns]
    t = t.merge(cnt.reset_index(), on="ward_no", how="left")
    for c in cnt.columns:
        t[c] = t[c].fillna(0).astype(int)
    t["n_critical_facilities"] = t[list(cnt.columns)].sum(axis=1)
    t["critical_facilities_per_km2"] = t.n_critical_facilities / t.area_km2
    for yr, rep in reports_by_year.items():
        f = fac[~fac.duplicate_location_same_class].copy()
        f[f"near_{yr}"] = near_reported(f, rep[rep.placed], radius_m)
        nn = f[f[f"near_{yr}"]].groupby("ward_no").size().rename(f"n_facilities_near_reported_{yr}")
        t = t.merge(nn.reset_index(), on="ward_no", how="left")
        t[f"n_facilities_near_reported_{yr}"] = t[f"n_facilities_near_reported_{yr}"].fillna(0).astype(int)
    # normalised scores (min-max over wards with data) are SEPARATE columns
    for c in ("population_density_cdmp_per_km2", "road_surface_share", "critical_facilities_per_km2"):
        v = t[c].astype(float)
        t[c + "_score"] = (v - v.min()) / (v.max() - v.min())
    t["exposure_index_provisional"] = t[["population_density_cdmp_per_km2_score", "road_surface_share_score", "critical_facilities_per_km2_score"]].mean(axis=1, skipna=False)
    return t
