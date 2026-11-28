"""A. Overview and research summary; B. Study area and geospatial exploration."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import maps, ui
from lib import registry as R
from lib.data import aoi, wards


def render_overview():
    st.header("A. Overview and research summary")
    ui.badges("EXPLORATORY", "NOT VALIDATED")
    meta = R.js("aoi_meta", {})
    st.markdown(
        "**Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data. Chennai, Tamil Nadu, India.** "
        "The application brings together the project's accepted products:\n\n"
        "- **SUS-1:** relative terrain susceptibility;\n"
        "- **S1WC-2 and S1PE:** Sentinel-1 water-signature and bright-VV diagnostics;\n"
        "- **CHIRPS / IMD:** rainfall context;\n"
        "- **DEP2:** reported flood evidence, exposure and partial vulnerability;\n"
        "- **ML-EXP-1:** evidence-aware exploratory analytics.\n\n"
        "It explores where conditions, people, assets and reported flooding coincide. "
        "**It cannot say where it will flood, how likely flooding is, or how accurate any map is.** "
        "No independent mapped flood extent exists yet for any Sentinel-1 date.")
    integ = R.csv("integrated_csv")
    mlx = R.js("mlx_summary", {})
    ui.kpis([
        ("Study area (provisional OSM AOI)", f"{meta.get('area_km2', '?')} km²"),
        ("Analysis grid", "EPSG:32644 · 30 m · 1416×726"),
        ("GCC wards (TNGIS, analysis units)", "200"),
        ("Wards with ≥1 CDMP report 2021 / 2015", f"{int((integ.cdmp_records_2021 > 0).sum())} / {int((integ.cdmp_records_2015 > 0).sum())}" if integ is not None else "?"),
        ("Independent E1 flood extents", "0"),
    ])
    st.subheader("Main findings (all exploratory)")
    c15, c21 = R.csv("cmp2015"), R.csv("cmp2021")
    r15 = f"{c15[(c15.buffer_m == 50)].ratio_to_null.iloc[0]:.1f}×" if c15 is not None else "n/a"
    r21 = (f"{c21[c21.distance_threshold_m <= 100].ratio_to_null.min():.2f}–{c21[c21.distance_threshold_m <= 100].ratio_to_null.max():.2f}" if c21 is not None else "n/a")
    st.markdown(
        f"1. **Reported evidence (E3).** The GCC City Disaster Management Plan lists **561 inundated locations for 2021** and **306 for 2015**, at year-level timing. "
        f"The two independent 2015 sources (GCC list and crowd-flagged streets of 2 Dec 2015) agree spatially **{r15}** more often than a street-fabric null model.\n"
        f"2. **Sentinel-1.** The 2021 reported locations show **no association** with bright-VV components at 0–100 m (ratio {r21} to the null). "
        "This gives no support for using bright VV as flood evidence. S1WC-2 dark candidates are context only.\n"
        "3. **Exposure.** Two population sources disagree by a factor of **~3** (CDMP ward tables vs WorldPop 2020). They are kept separate.\n"
        "4. **Vulnerability** is **partial**: housing plus adaptive capacity only, with social sensitivity missing. It is sensitive to indicator choice.\n"
        )
    pb = R.csv("mlx_pb")
    if pb is not None:
        sig = pb[(pb.p_perm_one_sided < 0.05) & ~pb.feature_set.str.startswith("F0")]
        st.markdown(f"5. **ML-EXP-1:** {len(sig)} of {int((~pb.feature_set.str.startswith('F0')).sum())} indicator-model combinations rank reported wards above unlabelled wards "
                    "beyond a label-permutation null under zone-blocked, buffered cross-validation. "
                    + ("The current E3 labels therefore mostly reflect reporting, not a learnable physical signal. "
                       "This is a result, not a failure: it sets the data requirement for supervised flood ML." if len(sig) == 0 else
                       "Read these as associations with reporting, not prediction."))
    else:
        st.markdown("5. **ML-EXP-1:** not yet run in this checkout (`scripts/build_ward_analytics.py`).")
    if mlx:
        st.caption(f"ML-EXP-1 run: {mlx.get('version')} · {mlx.get('n_wards_multivariate')} wards in multivariate analysis · selected k = {mlx.get('k_selected')} · {ui.guard_text(mlx)[0]}")
    st.subheader("Component status")
    status = pd.DataFrame([
        ("Study area", "PROVISIONAL", "OSM-derived, ~435 km²; not the official GCC boundary"),
        ("SUS-1 susceptibility", "ACCEPTED WITH QUALIFICATIONS", "relative index; DSM not DTM; HAND proxy; not calibrated"),
        ("S1WC-2 Sentinel-1", "ACCEPTED (technical)", "8 dates QA_PASS; candidates not floodwater"),
        ("Flood reference evidence", "COMPLETE WITH LIMITATIONS", "E3 presence-only; no E1 extent"),
        ("Exposure", "COMPLETE WITH LIMITATIONS", "no building footprints; population sources conflict"),
        ("Vulnerability", "PARTIALLY COMPLETE", "social sensitivity missing"),
        ("Integrated ward comparison", "EXPLORATORY", "terciles; no risk score"),
        ("ML", "EXPLORATORY ANALYTICS ONLY", "no supervised flood model is defensible with current labels; RF v0 retired"),
    ], columns=["component", "status", "key limitation"])
    ui.table(status, height=320)
    lim = R.csv("limitations")
    if lim is not None:
        with st.expander("All recorded limitations and blockers"):
            ui.table(lim, height=420)
            ui.source(R.rel("limitations") + " (DEP2 documentation package)")
    ui.cannot_claim("flood probability, flood prediction, validated hazard or risk, accuracy/precision/recall/F1/IoU, or any ward being flood-free.")


def render_study_area():
    st.header("B. Study area and geospatial exploration")
    meta = R.js("aoi_meta", {})
    ver = str(meta.get("verification", "")).removeprefix("PROVISIONAL:").strip()
    ui.note(f"Study-area boundary: <b>{meta.get('kind', 'PROVISIONAL')}</b>. {ver} "
            "It is <b>not</b> the official Greater Chennai Corporation boundary. Analysis units are the 200 TNGIS GCC wards (431.99 km²), a different polygon set.")
    W = wards()
    c1, c2 = st.columns([1, 3])
    with c1:
        layers = st.multiselect("Raster layers", ["SUS-1 percentile", "Elevation (GLO-30 DSM)", "Slope", "HAND proxy", "SUS-1 domain (assessed / not assessed)"],
                                default=["SUS-1 percentile"])
        sel = st.selectbox("Highlight ward", ["(none)"] + [str(int(x)) for x in W.ward_no]) if W is not None else "(none)"
        st.markdown(maps.CRS_NOTE)
    m = maps.base_map()
    A = aoi()
    if A is not None:
        maps.add_aoi(m, A, "Study area (PROVISIONAL OSM AOI)")
    stack = R.P["sus_stack"]
    spec = {"SUS-1 percentile": (R.P["sus_pct"], dict(cmap="YlOrRd", vmin=0, vmax=100)),
            "Elevation (GLO-30 DSM)": (stack, dict(cmap="terrain", band=1)), "Slope": (stack, dict(cmap="magma", band=2)),
            "HAND proxy": (stack, dict(cmap="viridis", band=6)),
            "SUS-1 domain (assessed / not assessed)": (R.P["sus_domain"], dict(categorical={1: ("#c7e9c0", "scored"), 2: ("#6baed6", "water signature: not assessed"),
                                                                                              3: ("#fd8d3c", "missing: not assessed"), 255: ("none", "outside")}))}
    for name in layers:
        p, kw = spec[name]
        if p.is_file():
            maps.add_raster(m, p, name, show=True, **kw)
    if W is not None:
        import folium
        folium.GeoJson(maps.display_geoms(W, ["ward_no", "zone_no", "area_km2"]), name="GCC wards (TNGIS)",
                       style_function=lambda x: {"color": "#c0392b", "weight": 0.6, "fillOpacity": 0},
                       tooltip=folium.GeoJsonTooltip(fields=["ward_no", "zone_no", "area_km2"], aliases=["Ward", "Zone", "Area km²"], localize=True)).add_to(m)
        if sel != "(none)":
            g = W[W.ward_no == int(sel)].to_crs("EPSG:4326")
            folium.GeoJson(g[["geometry"]], name=f"Ward {sel}", style_function=lambda x: {"color": "#000", "weight": 3, "fillOpacity": 0.05}).add_to(m)
            b = g.total_bounds
            m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
    maps.legend_html(m, "Layers", [("#1f4e79", "Provisional study area (dashed)"), ("#c0392b", "GCC ward boundary"),
                                   ("#cbd2d9", "not assessed / no data: transparent or grey, never low")])
    with c2:
        maps.render(m)
    ui.source("study_area_wgs84.geojson (OSM Nominatim, provisional); TNGIS gcc_ward_boundary; SUS-1 rasters (outputs/susceptibility_v1); Copernicus GLO-30 DSM.")
    if sel != "(none)" and W is not None:
        f = R.csv("mlx_features")
        if f is not None:
            st.subheader(f"Ward {sel}: indicator profile")
            ui.table(f[f.ward_no == int(sel)].T.reset_index().rename(columns={"index": "indicator"}), height=420)
