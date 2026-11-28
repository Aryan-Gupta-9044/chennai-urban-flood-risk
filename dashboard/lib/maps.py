"""Folium map builders. Rasters are reprojected to EPSG:4326 for display only (nearest neighbour); analysis stays in
EPSG:32644. NoData / not assessed is transparent and called out in the legend - never drawn as a low value."""
from __future__ import annotations

import numpy as np
import streamlit as st

CRS_NOTE = "Analysis CRS EPSG:32644, 30 m grid (1416 x 726); display reprojected to EPSG:4326 (nearest neighbour)."


@st.cache_data(show_spinner=False)
def raster_overlay(path, cmap="YlOrRd", vmin=None, vmax=None, categorical=None, band=1, alpha=0.78):
    import matplotlib
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds
    with rasterio.open(path) as ds:
        arr = ds.read(band).astype("float32")
        nd = ds.nodata
        tr, w, h = calculate_default_transform(ds.crs, "EPSG:4326", ds.width, ds.height, *ds.bounds)
        src = np.where(arr == nd, np.nan, arr) if nd is not None else arr
        dst = np.full((h, w), np.nan, dtype="float32")
        reproject(src, dst, src_transform=ds.transform, src_crs=ds.crs, dst_transform=tr, dst_crs="EPSG:4326",
                  resampling=Resampling.nearest, src_nodata=np.nan, dst_nodata=np.nan)
        b = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    rgba = np.zeros((h, w, 4), dtype="float32")
    if categorical:
        for code, (hexcol, _) in categorical.items():
            m = dst == code
            c = matplotlib.colors.to_rgba(hexcol)
            rgba[m] = c
            rgba[m, 3] = alpha if hexcol != "none" else 0
    else:
        cm = matplotlib.colormaps[cmap]
        lo = np.nanpercentile(dst, 2) if vmin is None else vmin
        hi = np.nanpercentile(dst, 98) if vmax is None else vmax
        rgba = cm(np.clip((dst - lo) / max(hi - lo, 1e-9), 0, 1)).astype("float32")
        rgba[..., 3] = np.where(np.isfinite(dst), alpha, 0)
        categorical = {"_range": (float(lo), float(hi))}
    return (rgba * 255).astype("uint8"), [[b[1], b[0]], [b[3], b[2]]], categorical


# ---- shared map frame --------------------------------------------------------------------------------------
# Basemaps: OpenStreetMap standard tiles need no API key and are the default. CARTO Positron was the v1 default but
# its tile server answered "API KEY REQUIRED" on the owner's machine (FINAL-02 review), so it is no longer offered.
# Thematic layers never depend on tiles: they are drawn from local project files, a local ward/AOI reference layer is
# always drawn, and a banner appears inside the map when basemap tiles fail to load.
BASEMAPS = {
    "OpenStreetMap": dict(tiles="OpenStreetMap", attr=None, label="Basemap: OpenStreetMap (© OpenStreetMap contributors)"),
}
FALLBACK_EXTENT = (80.13, 12.85, 80.34, 13.24)   # used only if the AOI file is missing; derived from the AOI bounds
REGION_PAD = 0.35                                  # degrees around the AOI the user can pan/zoom within


def overlay_opacity() -> float:
    """Global overlay opacity factor chosen in the sidebar (1.0 = as designed)."""
    try:
        return float(st.session_state.get("ov_opacity", 1.0))
    except Exception:  # noqa: BLE001
        return 1.0


@st.cache_data(show_spinner=False)
def aoi_extent_wgs84(path=None):
    """(minx, miny, maxx, maxy) of the provisional AOI in EPSG:4326, read from the project file."""
    try:
        import geopandas as gpd
        from . import registry as R
        p = path or (str(R.P["aoi_wgs84"]) if R.exists("aoi_wgs84") else None)
        if p:
            g = gpd.read_file(p)
            g = g.to_crs("EPSG:4326") if g.crs and g.crs.to_epsg() != 4326 else g
            return tuple(float(x) for x in g.total_bounds)
    except Exception:  # noqa: BLE001
        pass
    return FALLBACK_EXTENT


def base_map(center=None, zoom=11, basemap="OpenStreetMap", extent=None, reference=True):
    """Leaflet frame fitted to the AOI, limited to the Chennai region (no accidental zoom-out to the globe), metric scale,
    scroll-wheel zoom off (page scrolling no longer zooms the map; use +/- or double-click)."""
    import folium
    x0, y0, x1, y1 = extent or aoi_extent_wgs84()
    m = folium.Map(location=list(center) if center else [(y0 + y1) / 2, (x0 + x1) / 2], zoom_start=zoom, tiles=None,
                   control_scale=False, min_zoom=9, max_zoom=18, max_bounds=True,
                   min_lat=y0 - REGION_PAD, max_lat=y1 + REGION_PAD, min_lon=x0 - REGION_PAD, max_lon=x1 + REGION_PAD,
                   scrollWheelZoom=False, zoomSnap=0.25, font_size="12px")
    b = BASEMAPS.get(basemap, BASEMAPS["OpenStreetMap"])
    folium.TileLayer(b["tiles"], name=b["label"], attr=b["attr"], max_zoom=19).add_to(m)
    m.fit_bounds([[y0, x0], [y1, x1]], padding=(10, 10))
    _add_frame_controls(m)
    if reference:
        add_reference(m)
    return m


def _add_frame_controls(m):
    """Metric-only scale bar, a north arrow and a basemap-failure banner (pure Leaflet JS; no external requests)."""
    from branca.element import MacroElement, Template
    js = """{% macro script(this, kwargs) %}
    (function(){
      var map = {{ this._parent.get_name() }};
      L.control.scale({metric: true, imperial: false, maxWidth: 160, position: 'bottomright'}).addTo(map);
      var na = L.control({position: 'topleft'});
      na.onAdd = function(){ var d = L.DomUtil.create('div', 'north-arrow');
        d.innerHTML = '<div style="background:rgba(255,255,255,.9);border:1px solid #888;border-radius:4px;padding:1px 6px;font:bold 12px Arial;text-align:center;line-height:13px">&#9650;<br>N</div>'; return d; };
      na.addTo(map);
      var banner = L.control({position: 'bottomright'}); var shown = false;
      banner.onAdd = function(){ var d = L.DomUtil.create('div', 'tile-banner');
        d.style.cssText = 'display:none;background:#fff8e1;color:#5c3c00;border:1px solid #b7791f;border-radius:4px;padding:4px 8px;font:12px Arial;max-width:320px';
        d.innerHTML = 'Basemap tiles could not be loaded (offline or blocked). All thematic layers on this map are drawn from local project files.';
        return d; };
      banner.addTo(map);
      var errs = 0, oks = 0;
      map.eachLayer(function(l){ if (l instanceof L.TileLayer) {
        l.on('tileerror', function(){ errs++; if (!shown && errs >= 3 && oks === 0) { banner.getContainer().style.display = 'block'; shown = true; } });
        l.on('tileload', function(){ oks++; if (shown) { banner.getContainer().style.display = 'none'; shown = false; } });
      }});
      window.__mapState = function(){ return {zoom: map.getZoom(), center: map.getCenter(), bounds: map.getBounds().toBBoxString(), tileErrors: errs, tileLoads: oks}; };
    })();
    {% endmacro %}"""
    e = MacroElement()
    e._template = Template(js)
    m.add_child(e)


@st.cache_data(show_spinner=False)
def _reference_geojson(path):
    import geopandas as gpd
    g = gpd.read_file(path)[["geometry"]]
    g["geometry"] = g.geometry.simplify(5)  # display only: 5 m tolerance, far below the 30 m analysis grid
    return g.to_crs("EPSG:4326").to_json()


def add_reference(m, label="Reference: GCC ward outlines (TNGIS, local file)"):
    """Always-on local reference layer so the map stays readable without basemap tiles."""
    import folium
    from . import registry as R
    if R.exists("wards_gpkg"):
        folium.GeoJson(_reference_geojson(str(R.P["wards_gpkg"])), name=label, control=True, interactive=False,
                       style_function=lambda x: {"color": "#7b8794", "weight": 0.6, "fill": False}).add_to(m)


def display_geoms(gdf, cols):
    """EPSG:4326 copy for display: invalid geometries repaired with make_valid, 5 m simplification (display only)."""
    from shapely import make_valid
    g = gdf[cols + ["geometry"]].copy()
    bad = ~g.geometry.is_valid
    if bad.any():
        g.loc[bad, "geometry"] = g.loc[bad, "geometry"].apply(make_valid)
    if g.crs is not None and not g.crs.is_geographic:
        g["geometry"] = g.geometry.simplify(5)
    return g.to_crs("EPSG:4326")


def geometry_check(gdf, key="ward_no", value_col=None, extent=None):
    """Data checks behind a ward map: CRS, validity, empties, duplicate keys, extent, join coverage."""
    x0, y0, x1, y1 = extent or aoi_extent_wgs84()
    out = {"crs": str(gdf.crs), "n_features": int(len(gdf)), "n_invalid": int((~gdf.geometry.is_valid).sum()),
           "n_empty": int(gdf.geometry.is_empty.sum()), "n_duplicate_keys": int(gdf[key].duplicated().sum()) if key in gdf else None}
    b = gdf.to_crs("EPSG:4326").total_bounds if len(gdf) else [float("nan")] * 4
    out["bounds_wgs84"] = [round(float(v), 4) for v in b]
    tol = 0.05
    out["within_study_region"] = bool(b[0] >= x0 - tol and b[1] >= y0 - tol and b[2] <= x1 + tol and b[3] <= y1 + tol)
    if value_col and value_col in gdf:
        out["n_with_value"] = int(gdf[value_col].notna().sum())
        out["n_missing_value"] = int(gdf[value_col].isna().sum())
    out["ok"] = out["n_invalid"] == 0 and out["n_empty"] == 0 and not out["n_duplicate_keys"] and out["within_study_region"]
    return out


def add_aoi(m, aoi_gdf, label):
    import folium
    folium.GeoJson(aoi_gdf[["geometry"]], name=label, style_function=lambda x: {"color": "#1f4e79", "weight": 2.5, "dashArray": "6 4", "fillOpacity": 0},
                   tooltip=label).add_to(m)


def add_raster(m, path, name, show=False, **kw):
    import folium
    img, bnds, legend = raster_overlay(str(path), **kw)
    folium.raster_layers.ImageOverlay(img, bnds, name=name, opacity=overlay_opacity(), show=show).add_to(m)
    return legend


UNITS = {"population_density_cdmp_per_km2": "persons/km²", "pop_density_cdmp": "persons/km²", "sus_a_mean_pct": "percentile 0–100 (relative)",
         "reported_2021_per_km2": "listed locations/km²", "area_km2": "km²", "road_surface_share": "share 0–1", "facilities_per_km2": "facilities/km²"}


def ward_choropleth(m, gdf, col, name, cmap="YlOrRd", fields=None, aliases=None, show=True, nodata_label="no data / not assessed",
                    scheme="auto", k=6, units=None):
    """Ward choropleth. scheme='quantile' uses k quantile classes (readable for skewed variables such as density);
    'linear' a continuous ramp; 'auto' picks quantile when |skew| > 1. NaN wards are hatched grey and labelled."""
    import branca.colormap as bcm
    import folium
    v = gdf[col].astype(float)
    ok = v.notna()
    lo, hi = (float(v[ok].min()), float(v[ok].max())) if ok.any() else (0.0, 1.0)
    hi = hi if hi > lo else lo + 1
    base = {"YlOrRd": bcm.linear.YlOrRd_09, "Blues": bcm.linear.Blues_09, "Purples": bcm.linear.Purples_09, "OrRd": bcm.linear.OrRd_09,
            "Greens": bcm.linear.Greens_09, "viridis": bcm.linear.viridis}.get(cmap, bcm.linear.YlOrRd_09)
    if scheme == "auto":
        scheme = "quantile" if ok.sum() > 10 and abs(float(v[ok].skew())) > 1 and v[ok].nunique() > k else "linear"
    unit = units if units is not None else ("" if "(" in name else UNITS.get(col, ""))
    if scheme == "quantile":
        qs = sorted(set(float(x) for x in np.nanquantile(v[ok], np.linspace(0, 1, k + 1))))
        ramp = base.scale(0, 1)
        ncls = len(qs) - 1
        cols = [ramp(0.08 + 0.92 * i / max(ncls - 1, 1)) for i in range(ncls)]   # colours evenly spaced by class, not value

        def cmap_obj(x, _q=qs, _c=cols):
            i = int(np.searchsorted(_q, x, side="right")) - 1
            return _c[min(max(i, 0), len(_c) - 1)]
        caption = f"{name}{' (' + unit + ')' if unit else ''}: {len(qs) - 1} quantile classes"
    else:
        cmap_obj = base.scale(lo, hi)
        caption = f"{name}{' (' + unit + ')' if unit else ''}"
    if scheme != "quantile":
        cmap_obj.caption = caption
    g = gdf.copy()
    g["_v"] = v
    op = overlay_opacity()

    def style(feat):
        x = feat["properties"].get("_v")
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return {"fillColor": "#cbd2d9", "color": "#7b8794", "weight": 0.5, "fillOpacity": 0.55 * op, "dashArray": "3 3"}
        return {"fillColor": cmap_obj(x), "color": "white", "weight": 0.4, "fillOpacity": 0.78 * op}
    flds = fields or ["ward_no", col]
    g[flds] = g[flds].astype(object).where(g[flds].notna(), nodata_label)
    folium.GeoJson(display_geoms(g, flds + ["_v"]), name=name, style_function=style, show=show,
                   tooltip=folium.GeoJsonTooltip(fields=flds, aliases=aliases or flds, localize=True)).add_to(m)
    nodata_row = [("#cbd2d9", f"{nodata_label} ({int((~ok).sum())} wards)")] if (~ok).any() else []
    if scheme == "quantile":
        rows = [(cmap_obj((qs[i] + qs[i + 1]) / 2), f"{_fmt(qs[i])} – {_fmt(qs[i + 1])}") for i in range(len(qs) - 1)]
        legend_html(m, caption, rows + nodata_row)
    else:
        cmap_obj.add_to(m)
        if nodata_row:
            legend_html(m, "Ward map", nodata_row)


def _fmt(x: float) -> str:
    ax = abs(x)
    return f"{x:,.0f}" if ax >= 100 else (f"{x:.1f}" if ax >= 10 else f"{x:.2f}")


def ward_categorical(m, gdf, col, name, classes, fields=None, aliases=None, show=True, nodata_label="not assessed"):
    """Categorical ward map. classes: {value: (css colour, label)}. Wards with no value are hatched grey."""
    import folium
    g = gdf.copy()
    g["_v"] = g[col]
    op = overlay_opacity()

    def style(feat):
        x = feat["properties"].get("_v")
        try:
            key = int(x)
        except (TypeError, ValueError):
            key = None
        if key is None or key not in classes:
            return {"fillColor": "#cbd2d9", "color": "#7b8794", "weight": 0.5, "fillOpacity": 0.55 * op, "dashArray": "3 3"}
        return {"fillColor": classes[key][0], "color": "#ffffff", "weight": 0.6, "fillOpacity": 0.8 * op}
    flds = fields or ["ward_no", col]
    g[flds] = g[flds].astype(object).where(g[flds].notna(), nodata_label)
    g["_v"] = g["_v"].astype(object).where(g["_v"].notna(), None)
    folium.GeoJson(display_geoms(g, flds + ["_v"]), name=name, style_function=style, show=show,
                   tooltip=folium.GeoJsonTooltip(fields=flds, aliases=aliases or flds, localize=True)).add_to(m)
    legend_html(m, name, [c for c in classes.values()] + [("#cbd2d9", nodata_label)])


def legend_html(m, title, items):
    """items: list of (css colour, label)."""
    from branca.element import MacroElement, Template
    rows = "".join(f"<div><span style='display:inline-block;width:12px;height:12px;background:{c};border:1px solid #555;margin-right:6px'></span>{lab}</div>" for c, lab in items)
    html = f"""{{% macro html(this, kwargs) %}}<div style='position:fixed;bottom:22px;left:12px;z-index:9999;background:white;padding:8px 10px;border:1px solid #999;
    border-radius:6px;font-size:12px;line-height:1.45;color:#1f2933;max-width:320px;box-shadow:0 1px 4px rgba(0,0,0,.25)'><b>{title}</b>{rows}</div>{{% endmacro %}}"""
    e = MacroElement()
    e._template = Template(html)
    m.get_root().add_child(e)


VENDOR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "vendor"
_INLINE = {  # CDN asset -> vendored file (inlined so maps work offline; licences in dashboard/static/vendor)
    "leaflet.js": ("script", "leaflet.js"), "leaflet.css": ("style", "leaflet.css"),
    "jquery-3.7.1.min.js": ("script", "jquery.min.js"), "d3.min.js": ("script", "d3.min.js"),
}
_DROP = ("bootstrap", "fontawesome", "awesome-markers", "awesome.rotate")   # not used by these maps


def offline_html(html: str) -> str:
    """Replace CDN <script>/<link> tags with inline vendored copies; drop unused CDN assets. Basemap tiles still need internet."""
    import re

    def repl(mo):
        tag = mo.group(0)
        url = mo.group(1)
        name = url.rsplit("/", 1)[-1]
        if any(d in url for d in _DROP):
            return ""
        if name in _INLINE and (VENDOR / _INLINE[name][1]).is_file():
            kind, fn = _INLINE[name]
            body = (VENDOR / fn).read_text(encoding="utf-8")
            if kind == "style":  # relative image URLs do not resolve inside the component iframe: embed them
                import base64
                for img in ("layers-2x.png", "layers.png", "marker-icon.png"):
                    f = VENDOR / "images" / img
                    if f.is_file():
                        body = body.replace(f"url(images/{img})", "url(data:image/png;base64," + base64.b64encode(f.read_bytes()).decode() + ")")
            return f"<script>{body}</script>" if kind == "script" else f"<style>{body}</style>"
        return tag
    html = re.sub(r'<script[^>]*src="(https?://[^"]+)"[^>]*>\s*</script>', repl, html)
    html = re.sub(r'<link[^>]*href="(https?://[^"]+)"[^>]*/?>', repl, html)
    # folium sets .leaflet-container{font-size:1rem}; restore Leaflet's compact 12px controls and a sans-serif legend
    fix = ("<style>.leaflet-container{font-size:12px!important;font-family:'Helvetica Neue',Arial,sans-serif;background:#eef1f4}"
           "body{font-family:'Helvetica Neue',Arial,sans-serif}.leaflet-control-layers{color:#1f2933}"
           ".leaflet-control-layers-expanded{max-height:70%;overflow-y:auto}</style>")
    return html.replace("</head>", fix + "</head>", 1) if "</head>" in html else fix + html


def render(m, height=620):
    """Add the layer control and embed the map. Uses st.iframe (Streamlit >= 1.52) and falls back to the deprecated
    components.html on older versions; both run the same self-contained HTML."""
    import folium
    folium.LayerControl(collapsed=True, position="topright").add_to(m)
    html = offline_html(m.get_root().render())
    if hasattr(st, "iframe") and "HTML string" in (st.iframe.__doc__ or ""):
        st.iframe(html, height=height)
    else:  # pragma: no cover - older Streamlit
        import streamlit.components.v1 as components
        components.html(html, height=height)
