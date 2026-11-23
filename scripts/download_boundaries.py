#!/usr/bin/env python
"""Module A1 - Chennai study-area boundary.
The OSM-geocoded boundary is PROVISIONAL until compared with the official Greater Chennai Corporation boundary.
To use an official file, put it in data/external/boundary/ (GeoJSON/Shapefile/GPKG/ZIP) and re-run."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
from shapely.geometry import box
from src.utils import status, paths
from src.utils.config import load_settings
from src.utils.logging_setup import get_logger
from src.geospatial.vector_io import find_vector_files, read_vector
from src.visualization import maps, plots
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

MODULE = "A1"


def main():
    t0 = time.time()
    log = get_logger("A1_boundary")
    paths.ensure_dirs()
    cfg = load_settings()
    kind, source, verification, note = None, None, None, ""
    gdf = None

    user = find_vector_files(paths.DATA_EXT / "boundary")
    if user:
        gdf = read_vector(user[0])
        if gdf.crs is None:
            gdf = gdf.set_crs(4326)
            note = "File had no CRS; assumed EPSG:4326. "
        kind = paths.external_kind()
        source = f"data/external/boundary/{user[0].name}"
        verification = "User-supplied. Confirm it is the official GCC boundary and record its source/date."
        log.info("using user-supplied boundary %s", user[0].name)
    else:
        raw = paths.DATA_RAW / "chennai_boundary_osm.geojson"
        try:
            if raw.exists():
                gdf = gpd.read_file(raw)
                log.info("using cached raw OSM boundary")
            else:
                import osmnx as ox
                log.info("geocoding '%s' via OpenStreetMap Nominatim ...", cfg["place_query"])
                g = ox.geocode_to_gdf(cfg["place_query"])
                g = g[g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
                if g.empty:
                    raise RuntimeError("geocoder returned no polygon")
                keep = [c for c in ("display_name", "osm_type", "osm_id", "class", "type") if c in g.columns]
                gdf = g[keep + ["geometry"]].copy()
                gdf.to_file(raw, driver="GeoJSON")  # raw data: written once, never overwritten
                log.info("saved raw boundary -> %s", paths.rel(raw))
            kind = status.PROVISIONAL
            source = "OpenStreetMap (Nominatim geocode via osmnx)"
            verification = ("PROVISIONAL: not verified against the official Greater Chennai Corporation "
                            "administrative boundary. Do not treat as official.")
        except Exception as e:
            log.warning("OSM boundary unavailable: %s", str(e)[:200])
            note = f"OSM boundary failed ({str(e)[:120]}). "

    fallback = False
    if gdf is None:
        # Second choice: union of the real DataMeet ward polygons (clearly labelled; NOT the official boundary)
        try:
            from src.data_acquisition.wards import acquire_wards
            from src.geospatial.vector_io import read_vector as _rv
            wp, wprov = acquire_wards(cfg, log)
            if wp is not None:
                wg = _rv(wp)
                if wg.crs is None:
                    wg = wg.set_crs(4326)
                wg = wg.to_crs(4326)
                wg["geometry"] = wg.geometry.buffer(0)
                u = wg.geometry.union_all() if hasattr(wg.geometry, "union_all") else wg.geometry.unary_union
                u = u.buffer(0.0003).buffer(-0.0003)  # close ~30 m sliver gaps between adjacent wards
                gdf = gpd.GeoDataFrame({"display_name": ["Union of ward polygons"]}, geometry=[u], crs=4326)
                kind = "PROVISIONAL-WARD-UNION"
                source = f"Union of ward polygons ({wprov.get('source')}); OSM boundary was unavailable"
                verification = ("PROVISIONAL: dissolved from the ward file, not verified against the official "
                                "Greater Chennai Corporation boundary.")
        except Exception as e:
            log.warning("ward-union fallback failed: %s", str(e)[:150])
    if gdf is None:
        # Wards union is NOT used here (wards are processed later); use a rough bbox so DEM/landcover can still run.
        fallback = True
        b = cfg["fallback_bbox_wgs84"]
        gdf = gpd.GeoDataFrame({"display_name": ["ROUGH BBOX placeholder - not a real boundary"]},
                               geometry=[box(*b)], crs=4326)
        kind = "PLACEHOLDER"
        source = "config/settings.json fallback_bbox_wgs84 (rough rectangle around Chennai)"
        verification = "NOT A BOUNDARY: rectangle used only so raster modules can run. Replace with a real boundary."

    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.buffer(0)
    wgs = gdf.copy()
    utm = gdf.to_crs(cfg["analysis_epsg"])
    area = float(utm.geometry.area.sum() / 1e6)
    lo, hi = cfg["expected_area_km2_range"]
    sanity = "OK" if lo <= area <= hi else f"WARN: area {area:.0f} km2 outside expected {lo}-{hi} km2"
    wgs.to_file(paths.DATA_PROC / "study_area_wgs84.geojson", driver="GeoJSON")
    utm.to_file(paths.DATA_PROC / "study_area_utm44n.geojson", driver="GeoJSON")
    meta = {"kind": kind, "source": source, "verification": verification, "area_km2": round(area, 2),
            "native_crs_checked": "EPSG:4326 (all inputs reprojected)", "analysis_crs": f"EPSG:{cfg['analysis_epsg']}",
            "bounds_wgs84": [round(v, 5) for v in wgs.total_bounds], "area_sanity": sanity, "note": note}
    (paths.DATA_PROC / "study_area_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("area %.1f km2 (%s); bounds %s", area, sanity, meta["bounds_wgs84"])

    # Static map
    fig, ax = plt.subplots(figsize=(7, 7.5))
    utm.plot(ax=ax, facecolor="#cfe8f3", edgecolor="#1f4e79", linewidth=1.5)
    ax.set_title(f"Study area ({kind}) - {area:.0f} km2\nEPSG:{cfg['analysis_epsg']}", fontsize=11)
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.ticklabel_format(style="plain", useOffset=False)
    ax.tick_params(labelsize=7)
    fig.text(0.5, 0.01, verification[:110], ha="center", fontsize=7, color="#a00")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    f1 = paths.OUT_FIG / "study_area.png"
    fig.savefig(f1, dpi=200)
    plt.close(fig)
    f2 = paths.OUT_MAPS / "study_area.html"
    maps.boundary_map(wgs, f2, f"Study area: {kind}", status_html=f"<br><small>{verification}</small>")

    state = status.PARTIAL if (fallback or str(kind).startswith("PROVISIONAL")) else status.COMPLETED
    msg = (f"{kind} boundary, {area:.0f} km2. {verification} {note}").strip()
    if fallback:
        msg = "Boundary download failed; rough bounding box used as placeholder. " + msg
    status.record(MODULE, state, msg, files=[paths.rel(f1), paths.rel(f2), "data/processed/study_area_wgs84.geojson",
                                              "data/processed/study_area_utm44n.geojson"],
                  datasets=[{"name": "Chennai study-area boundary", "kind": kind, "source": source,
                             "path": "data/processed/study_area_wgs84.geojson"}],
                  requirements=([] if not str(kind).startswith("PROVISIONAL") else
                                ["Compare with the official GCC boundary; if different, place the official file in "
                                 "data/external/boundary/ and re-run."]) +
                               (["Run again with internet access to fetch the real boundary."] if fallback else []),
                  extra=meta, seconds=time.time() - t0)
    log.info("A1 state: %s", state)


if __name__ == "__main__":
    main()
