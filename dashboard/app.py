"""Initial Streamlit dashboard. Shows only what the pipeline actually generated."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Chennai Flood Risk - B794", layout="wide")
PROC, FIG, TAB, REP = (ROOT / "data" / "processed", ROOT / "outputs" / "figures",
                       ROOT / "outputs" / "tables", ROOT / "outputs" / "reports")
COL = {"COMPLETED": "#1a7f37", "PARTIALLY COMPLETED": "#b7791f", "BLOCKED": "#c0392b", "NOT STARTED": "#777"}


def jload(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


status = jload(REP / "status.json", {"modules": {}})["modules"]
meta = jload(PROC / "study_area_meta.json", {})

st.title("Integrated Geospatial Framework for Urban Flood Risk - Chennai (B794)")
st.caption("Initial foundation dashboard. Every layer below is read from files the pipeline generated; "
           "nothing is shown that was not produced.")
if not status:
    st.warning("No pipeline outputs yet. Run:  powershell -NoProfile -ExecutionPolicy Bypass -File .\\run.ps1")
if meta:
    box = st.error if meta.get("kind") in ("PLACEHOLDER",) else st.info
    box(f"Study area: **{meta.get('kind')}** - {meta.get('verification')}  (area {meta.get('area_km2')} km2)")

t_status, t_map, t_layers, t_tables = st.tabs(["Processing status", "Map", "Layers & charts", "Tables & inventory"])

with t_status:
    for mid, m in sorted(status.items()):
        c = COL.get(m["state"], "#555")
        st.markdown(f"**{mid} - {m['title']}** &nbsp; <span style='color:white;background:{c};padding:2px 8px;"
                    f"border-radius:4px'>{m['state']}</span>", unsafe_allow_html=True)
        st.write(m.get("message", ""))
        if m.get("requirements") and m["state"] != "COMPLETED":
            with st.expander("What is still needed"):
                for r in m["requirements"]:
                    st.write("- " + r)


@st.cache_data(show_spinner=False)
def overlay(path, kind, vmin=None, vmax=None):
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
    import matplotlib
    cm = matplotlib.colormaps[kind]
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype("float32")
        nd = ds.nodata
        tr, w, h = calculate_default_transform(ds.crs, "EPSG:4326", ds.width, ds.height, *ds.bounds)
        dst = np.full((h, w), np.nan, dtype="float32")
        src = np.where(arr == nd, np.nan, arr)
        reproject(src, dst, src_transform=ds.transform, src_crs=ds.crs, dst_transform=tr, dst_crs="EPSG:4326",
                  resampling=Resampling.nearest, src_nodata=np.nan, dst_nodata=np.nan)
        b = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    lo = np.nanpercentile(dst, 2) if vmin is None else vmin
    hi = np.nanpercentile(dst, 98) if vmax is None else vmax
    rgba = cm(np.clip((dst - lo) / max(hi - lo, 1e-9), 0, 1))
    rgba[..., 3] = np.where(np.isfinite(dst), 0.75, 0)
    return (rgba * 255).astype("uint8"), [[b[1], b[0]], [b[3], b[2]]]


with t_map:
    import folium
    import geopandas as gpd
    sa = PROC / "study_area_wgs84.geojson"
    if not sa.exists():
        st.info("Study-area boundary not generated yet.")
    else:
        g = gpd.read_file(sa)
        c = g.geometry.union_all().centroid if hasattr(g.geometry, "union_all") else g.geometry.unary_union.centroid
        m = folium.Map(location=[c.y, c.x], zoom_start=11, tiles="CartoDB positron")
        LAY = [("Elevation (m)", "dem_elevation_utm44n_30m.tif", "terrain"), ("Slope (deg)", "slope_deg_utm44n_30m.tif", "magma"),
               ("Built-up fraction", "builtup_fraction_utm44n_30m.tif", "Reds"),
               ("Rainfall event total (mm)", "rainfall_event_total_mm_utm44n_30m.tif", "Blues"),
               ("Flood susceptibility (RF v0)", "flood_susceptibility_rf_v0.tif", "YlOrRd")]
        LAY += [(f"Flood extent {p.stem.split('_utm')[0].replace('flood_extent_', '')} (SAR proxy)", p.name, "Blues")
                for p in sorted(PROC.glob("flood_extent_*_utm44n_30m.tif"))]
        avail = [(n, f, k) for n, f, k in LAY if (PROC / f).exists()]
        for n, f, k in avail:
            try:
                img, bnds = overlay(str(PROC / f), k)
                folium.raster_layers.ImageOverlay(img, bnds, name=n, opacity=0.8, show=False).add_to(m)
            except Exception as e:
                st.warning(f"Could not draw {n}: {e}")
        wf = PROC / "wards_wgs84.geojson"
        if wf.exists():
            w = gpd.read_file(wf)
            f = [x for x in ("ward_id", "ward_name", "area_km2") if x in w.columns]
            folium.GeoJson(w[f + ["geometry"]], name="Wards", tooltip=folium.GeoJsonTooltip(fields=f),
                           style_function=lambda x: {"color": "#c0392b", "weight": 0.8, "fillOpacity": 0.05}).add_to(m)
        else:
            st.caption("Ward boundaries not available (Module A2 blocked) - showing study area only.")
        folium.GeoJson(g[["geometry"]], name=f"Study area ({meta.get('kind', '?')})",
                       style_function=lambda x: {"color": "#1f4e79", "weight": 2.5, "fillOpacity": 0}).add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)
        components.html(m.get_root().render(), height=650)
        st.caption("Available raster layers: " + (", ".join(n for n, _, _ in avail) or "none yet"))

with t_layers:
    pngs = sorted(FIG.glob("*.png"))
    if not pngs:
        st.info("No figures yet.")
    cols = st.columns(2)
    for i, p in enumerate(pngs):
        cols[i % 2].image(str(p), caption=p.name, use_container_width=True)
    rt = TAB / "rainfall_daily_stats.csv"
    if rt.exists():
        st.subheader("Rainfall sample (CHIRPS)")
        st.bar_chart(pd.read_csv(rt).set_index("date")["mean_mm"])

with t_tables:
    for label, fn in [("Dataset inventory", "dataset_inventory.csv"), ("Module summary", "module_summary.csv"),
                      ("Flood event inventory", "flood_event_inventory.csv"), ("Ward statistics", "ward_statistics.csv"),
                      ("Ward terrain summary", "ward_terrain_summary.csv"), ("DEM statistics", "dem_statistics.csv"),
                      ("Land-cover statistics", "landcover_statistics.csv"), ("Feature table (sample)", "feature_table_sample.csv")]:
        p = TAB / fn
        if p.exists():
            st.subheader(label)
            st.dataframe(pd.read_csv(p), use_container_width=True, height=240)
    dq = REP / "data_quality_report.md"
    if dq.exists():
        st.subheader("Data quality report")
        st.markdown(dq.read_text(encoding="utf-8"))
