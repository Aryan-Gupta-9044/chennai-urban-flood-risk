# Map defects: diagnosis and fixes (FINAL-02)

The owner's six screenshots were not available here, so each reported symptom was diagnosed separately: data, CRS, geometry conversion, rendering and basemap.

The fixes are in the shared helper `dashboard/lib/maps.py`. All nine maps (sections B–J) use it, so no section has a one-off fix.

## Reported symptoms and root causes

| Symptom (owner screenshots) | What was checked | Finding | Fix |
|---|---|---|---|
| Section J map nearly blank; cluster polygons not visible | Ward GPKG CRS (EPSG:32644), validity, empties, duplicate `ward_no`, WGS84 bounds, cluster join | **Data are correct.** 200 valid polygons; 0 empty; 0 duplicate IDs; bounds 80.134–80.332 E, 12.852–13.235 N; clusters joined for 198 wards; 134 and 135 not clustered (incomplete indicators). The headless browser drew 403 polygon paths. | No data change. A map-data check is now printed under the J map and shown in section K, and a test asserts it. |
| Scale bar about 5,000 miles | Leaflet zoom and scale computation | A 5,000-mile bar means zoom ≈ 1–2, i.e. a world view. The v1 frame had **no zoom limits, no maximum bounds, and scroll-wheel zoom on**. Scrolling the page with the pointer over the map zooms Leaflet out to the globe, where Chennai's wards shrink to a dot and the map looks blank. The scale bar also showed imperial units. | `min_zoom=9`, `max_bounds` = AOI ± 0.35°, scroll-wheel zoom off (use +/- or double-click), fit to the AOI with `zoomSnap 0.25`, **metric-only** scale bar, north arrow |
| CARTO basemap showing "API KEY REQUIRED" (sections C, E, J) | Basemap configuration | The v1 frame made CARTO Positron the visible default. On the owner's machine its tile server refused the requests. Thematic layers did not depend on it, but the map looked broken. | **OpenStreetMap standard tiles are the default** (no key). CARTO was removed. A local ward-outline reference layer is always drawn. A banner appears inside the map if basemap tiles fail. |
| Maps unusable offline | Asset loading | Already fixed in FINAL-01: Leaflet, jQuery and d3 are vendored and inlined. FINAL-02 also inlines the layer-control icons. | Banner text: "All thematic layers on this map are drawn from local project files." |
| Deprecated `streamlit.components.v1.html` warning | Streamlit 1.67 source | `components.v1.html` is a deprecated alias of `st.iframe`, which accepts the same HTML string with scripts enabled. | `render()` uses `st.iframe` when the installed Streamlit documents HTML-string support, and otherwise keeps `components.html`. Verified with AppTest and a live headless browser. |

## Other map problems found and fixed during the audit

- **Section D, top-decile agreement legend.** It read "low code / high code (see review manifest)". It now shows the real codes from `scripts/susceptibility_review.py`: 0 neither, 1 A only, 2 C only, 3 both. Categorical colours replace the misleading viridis ramp.
- **Sections E, F and G, skewed ward variables.** Population density runs from 722 to 128,417 per km² on a linear ramp, which left almost every ward pale.
  - Skewed variables (|skew| > 1) now use **six quantile classes**, with colours evenly spaced by class.
  - The legend lists each class range.
  - Units are given in every caption, and the number of no-data wards is stated.
- **Raw column names.** Captions such as `population_density_cdmp_per_km2` are replaced by labels with units.
- **Performance.** Ward GeoJSON was 1.67 MB per layer. It is now about 0.6 MB, using 5 m simplification for display only (well below the 30 m analysis grid; analysis geometry is untouched).
  - The reference layer is cached.
  - Invalid geometries would be repaired with `make_valid` for display; none exist at present.
- **Opacity.** A sidebar control now scales the opacity of every thematic overlay.
- **Readability.** The legend is now 12 px, dark text on white with a shadow, and the layer-control text is dark.

## Verification

A headless Chrome probe (`mapprobe.py`) opened every map section and read Leaflet's state from inside each map iframe:

- **Zoom:** 10.75–11 in every map section (A has no map). Scale bar: 10 km.
- **Polygons drawn:** 204–405 paths per map.
- **Raster overlays:** present in B, D and I.
- **Banner:** shown, because the sandbox blocks tile servers. On a networked machine the OSM tiles load and the banner stays hidden.
- **Screenshots:** `docs/final02/screenshots/`.
- **Tests:** in `tests/test_final02.py`. They assert:
  - the OSM default and no CARTO;
  - the bounded extent and no wheel zoom;
  - the metric scale, the banner and the north arrow;
  - inlined assets and the `st.iframe` path;
  - the ward geometry check, the cluster-join coverage (only wards 134 and 135 missing) and `make_valid` repair.

## Not verifiable here

Whether OpenStreetMap tiles load on the owner's network. OSM's tile policy expects a valid Referer, and the browser sends the Streamlit page's origin. If they do not load, the banner explains it and every thematic layer remains visible.
