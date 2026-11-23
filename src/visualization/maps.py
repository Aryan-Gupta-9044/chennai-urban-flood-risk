import folium


def boundary_map(gdf_wgs84, path, label, wards_wgs84=None, ward_fields=None, status_html=""):
    c = gdf_wgs84.geometry.union_all().centroid if hasattr(gdf_wgs84.geometry, "union_all") \
        else gdf_wgs84.geometry.unary_union.centroid
    m = folium.Map(location=[c.y, c.x], zoom_start=11, tiles="CartoDB positron")
    folium.GeoJson(gdf_wgs84[["geometry"]], name=label,
                   style_function=lambda x: {"color": "#1f4e79", "weight": 2.5, "fillOpacity": 0.05}).add_to(m)
    if wards_wgs84 is not None and len(wards_wgs84):
        fields = [f for f in (ward_fields or []) if f in wards_wgs84.columns]
        folium.GeoJson(wards_wgs84[fields + ["geometry"]], name="Wards",
                       style_function=lambda x: {"color": "#c0392b", "weight": 0.8, "fillOpacity": 0.08},
                       tooltip=folium.GeoJsonTooltip(fields=fields) if fields else None).add_to(m)
    banner = (f'<div style="position:fixed;top:10px;left:50px;z-index:9999;background:white;padding:6px 10px;'
              f'border:1px solid #888;font:12px sans-serif;max-width:420px">{label}{status_html}</div>')
    m.get_root().html.add_child(folium.Element(banner))
    folium.LayerControl().add_to(m)
    m.save(str(path))
