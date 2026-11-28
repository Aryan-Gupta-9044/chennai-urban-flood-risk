"""D. Susceptibility; E. Exposure; F. Vulnerability; G. Integrated ward-level analysis."""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from lib import maps, ui
from lib import registry as R
from lib.data import aoi, gpkg, ward_table, wards


def _ward_map(col, name, cmap, fields, aliases, extra=None, nodata_label="no data / not assessed"):
    W = ward_table()
    m = maps.base_map()
    A = aoi()
    if A is not None:
        maps.add_aoi(m, A, "Study area (PROVISIONAL OSM AOI)")
    if W is not None and col in W:
        maps.ward_choropleth(m, W, col, name, cmap=cmap, fields=fields, aliases=aliases, nodata_label=nodata_label)
    if extra:
        extra(m)
    maps.render(m, height=560)


def render_susceptibility():
    st.header("D. Susceptibility analysis (SUS-1)")
    ui.badges("EXPLORATORY", "NOT VALIDATED")
    ui.note("SUS-1 is a <b>relative</b> terrain-susceptibility index: an equal-weight composite of seven DEM-derived indicator scores, ranked within this AOI. "
            "It is <b>not</b> a calibrated flood probability, not hazard and not risk. Its inputs: GLO-30 is a DSM (buildings and trees included); "
            "HAND is a Euclidean-nearest-drainage proxy; TWI largely restates slope and flow accumulation. "
            "Water-signature and missing cells are <b>not assessed</b>.")
    view = st.radio("View", ["Raster (30 m)", "Ward summary"], horizontal=True)
    if view == "Raster (30 m)":
        lay = st.selectbox("Layer", ["Baseline A percentile (accepted)", "Candidate C (no-TWI) minus A, percentile points (NOT adopted)", "Top-decile agreement C vs A", "Domain class"])
        m = maps.base_map()
        A = aoi()
        if A is not None:
            maps.add_aoi(m, A, "Study area (PROVISIONAL OSM AOI)")
        if lay.startswith("Baseline"):
            maps.add_raster(m, R.P["sus_pct"], lay, show=True, cmap="YlOrRd", vmin=0, vmax=100)
            maps.legend_html(m, "SUS-1 percentile (relative, 0-100)", [("#ffffcc", "0: lowest relative susceptibility in AOI"), ("#800026", "100: highest relative"), ("transparent", "not assessed: transparent")])
        elif lay.startswith("Candidate"):
            maps.add_raster(m, R.P["sus_c_diff"], lay, show=True, cmap="RdBu_r", vmin=-30, vmax=30)
            maps.legend_html(m, "C minus A (percentile points)", [("#2166ac", "-30 (C lower)"), ("#f7f7f7", "0"), ("#b2182b", "+30 (C higher)")])
        elif lay.startswith("Top"):
            cats = {0: ("none", "neither in top decile"), 1: ("#0072B2", "top decile in A only"), 2: ("#E69F00", "top decile in C only"),
                    3: ("#7b3294", "top decile in both A and C")}
            maps.add_raster(m, R.P["sus_c_agree"], lay, show=True, categorical=cats)
            maps.legend_html(m, "Top-decile agreement, C (no-TWI) vs A (codes from scripts/susceptibility_review.py)",
                             [(c, lab) for _, (c, lab) in cats.items() if c != "none"] + [("transparent", "neither / not scored: transparent")])
        else:
            cats = {1: ("#c7e9c0", "scored"), 2: ("#6baed6", "water signature: NOT ASSESSED"), 3: ("#fd8d3c", "missing: NOT ASSESSED"), 255: ("none", "outside AOI")}
            maps.add_raster(m, R.P["sus_domain"], lay, show=True, categorical=cats)
            maps.legend_html(m, "SUS-1 domain", [(c, lab) for _, (c, lab) in cats.items() if c != "none"])
        maps.render(m)
        st.caption(maps.CRS_NOTE)
    else:
        _ward_map("sus_a_mean_pct", "Ward mean SUS-1 percentile", "YlOrRd", ["ward_no", "sus_a_mean_pct", "sus_a_share_top_decile", "assessed_share"],
                  ["Ward", "Mean percentile", "Share in top decile", "Assessed share"])
        st.caption("Ward means use scored cells only; 'assessed share' gives the scored fraction of the ward's grid cells.")
    ui.source("outputs/susceptibility_v1 (accepted baseline A); outputs/susceptibility_review_v1 (candidate C, sensitivity only).")
    c1, c2 = st.columns(2)
    with c1:
        s = R.csv("sus_schemes")
        if s is not None:
            st.markdown("**Scheme comparison against baseline A**")
            ui.table(s.round(3), height=200)
        d = R.csv("sus_domain_summary")
        if d is not None:
            st.markdown("**Domain summary**")
            ui.table(d, height=260)
    with c2:
        v = R.csv("sus_vif")
        if v is not None:
            st.markdown("**Indicator redundancy (VIF / effective number)**")
            ui.table(v.round(3), height=260)
        st.markdown("**Stability of rankings**")
        r = R.csv("sus_stability")
        if r is not None:
            ui.table(r.round(3), height=200)
    corr = R.csv("sus_corr")
    if corr is not None:
        with st.expander("Indicator score correlation (Spearman)"):
            ui.table(corr.round(2), height=300)
    ui.cannot_claim("that a high-percentile cell flooded or will flood, or that candidate C is more accurate than A. No independent reference exists to compare them.")


def render_exposure():
    st.header("E. Exposure analysis")
    ui.badges("EXPLORATORY")
    ui.note("Exposure is <b>what is present</b>: people, roads and facilities. It says nothing about whether they flooded. "
            "Two population sources are shown <b>separately</b>: CDMP ward tables (reference year not stated) and WorldPop 2020 (100 m, complete for 94 wards only). "
            "They disagree by about 3×. There are no building footprints in this release.")
    col = st.selectbox("Ward indicator", {"population_density_cdmp_per_km2": "CDMP population density (persons/km²)", "wp_pop_density_2020": "WorldPop 2020 density (94 covered wards)",
                                          "road_surface_share": "Road-surface share", "critical_facilities_per_km2": "Critical facilities per km²",
                                          "exposure_index_provisional": "Provisional exposure index (exploratory)", "n_facilities_near_reported_2021": "Facilities ≤250 m of a 2021 report"}.keys(),
                       format_func=lambda k: {"population_density_cdmp_per_km2": "CDMP population density (persons/km²)", "wp_pop_density_2020": "WorldPop 2020 density (94 covered wards)",
                                              "road_surface_share": "Road-surface share", "critical_facilities_per_km2": "Critical facilities per km²",
                                              "exposure_index_provisional": "Provisional exposure index (exploratory)", "n_facilities_near_reported_2021": "Facilities ≤250 m of a 2021 report"}[k])
    e = R.csv("exposure")
    W = wards()
    if W is not None and e is not None:
        e = e.assign(wp_pop_density_2020=e.wp_population_2020 / e.area_km2)
        g = W[["ward_no", "geometry"]].merge(e, on="ward_no", how="left")
        show_fac = st.checkbox("Show critical facilities", value=False)
        m = maps.base_map()
        A = aoi()
        if A is not None:
            maps.add_aoi(m, A, "Study area (PROVISIONAL OSM AOI)")
        maps.ward_choropleth(m, g, col, EXPO_LABELS.get(col, col), cmap="Purples", fields=["ward_no", col, "wp_coverage_flag"], aliases=["Ward", EXPO_LABELS.get(col, col), "WorldPop coverage"],
                             nodata_label="not available (e.g. WorldPop not covering the ward): NOT zero")
        if show_fac:
            import folium
            f = gpkg("facilities")
            if f is not None:
                f = f[~f.duplicate_location_same_class & f.ward_no.notna()]
                cols = {"health": "#c0392b", "education": "#2b6cb0", "emergency": "#dd6b20", "administrative": "#4a5568", "public_service": "#2f855a"}
                fg = folium.FeatureGroup(name="Critical facilities (TNGIS + CDMP)")
                for r in f.to_crs("EPSG:4326").itertuples():
                    folium.CircleMarker([r.geometry.y, r.geometry.x], radius=2.5, color=cols.get(r.facility_group, "#333"), fill=True, fill_opacity=0.9,
                                        tooltip=f"{r.facility_class}: {r.facility_name}").add_to(fg)
                fg.add_to(m)
                maps.legend_html(m, "Facility groups", list((c, k) for k, c in cols.items()))
        maps.render(m, height=560)
    ui.source("DEP2 local run (B_exposure): GCC CDMP 2026 ward tables; WorldPop R2025A 2020 constrained (CC BY 4.0) clip; TNGIS layers; OSM (ODbL).")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Population sources compared (wards with both)**")
        if e is not None:
            d = e.dropna(subset=["population_cdmp", "wp_population_2020"])
            ch = alt.Chart(d).mark_circle(size=40, opacity=0.7).encode(
                x=alt.X("population_cdmp:Q", title="CDMP ward population"), y=alt.Y("wp_population_2020:Q", title="WorldPop 2020 (covered wards)"),
                tooltip=["ward_no", "population_cdmp", "wp_population_2020"]).properties(height=300)
            line = alt.Chart(pd.DataFrame({"x": [0, d.population_cdmp.max()], "y": [0, d.population_cdmp.max()]})).mark_line(color="grey", strokeDash=[4, 4]).encode(x="x", y="y")
            ui.chart(ch + line)
            st.caption(f"{len(d)} wards; median ratio WorldPop/CDMP = {(d.wp_population_2020 / d.population_cdmp).median():.2f}. Dashed: 1:1. Sources are never merged.")
    with c2:
        st.markdown("**Top exposed wards (provisional index)**")
        t = R.csv("top_exposed")
        if t is not None:
            ui.table(t.round(3), height=320)
    with st.expander("Population table reconciliation (CDMP zone totals)"):
        z = R.csv("pop_zone_chk")
        if z is not None:
            ui.table(z, height=300)
    st.caption("The provisional exposure index correlates about 0.9 with population density alone. In practice it is a density index.")


EXPO_LABELS = {"population_density_cdmp_per_km2": "CDMP population density (persons/km²)", "wp_pop_density_2020": "WorldPop 2020 density (persons/km², 94 covered wards)",
               "road_surface_share": "Road-surface share (0–1)", "critical_facilities_per_km2": "Critical facilities per km²",
               "exposure_index_provisional": "Provisional exposure index (0–1, exploratory)", "n_facilities_near_reported_2021": "Facilities ≤250 m of a 2021 report (count)"}
VULN_LABELS = {"vulnerability_index_provisional": "Provisional partial vulnerability index (0–1)", "component_housing_built_environment": "Housing / built-environment component (0–1)",
               "component_adaptive_capacity": "Adaptive-capacity component (0–1)", "slum_area_share": "Slum area share (0–1)",
               "dist_public_health_km": "Distance to public health facility (km)", "relief_capacity_per_1000": "Relief-centre capacity per 1,000 residents"}


def render_vulnerability():
    st.header("F. Vulnerability analysis (partial)")
    ui.badges("EXPLORATORY", "NOT VALIDATED")
    ui.note("This is a <b>partial</b> vulnerability framework: housing / built environment (slum area share) and adaptive capacity "
            "(distance to public health care, relief-centre capacity per 1,000 residents). <b>Social sensitivity is missing</b>: Census ward tables were not obtained, "
            "and the CDMP household counts failed QA. This is not a complete social-vulnerability assessment. Population density is exposure, not vulnerability.")
    col = st.selectbox("Layer", list(VULN_LABELS), format_func=lambda k: VULN_LABELS[k])
    v = R.csv("vuln")
    W = wards()
    if W is not None and v is not None:
        g = W[["ward_no", "geometry"]].merge(v, on="ward_no", how="left")
        m = maps.base_map()
        A = aoi()
        if A is not None:
            maps.add_aoi(m, A, "Study area (PROVISIONAL OSM AOI)")
        maps.ward_choropleth(m, g, col, VULN_LABELS.get(col, col), cmap="OrRd", fields=["ward_no", col, "data_complete"], aliases=["Ward", VULN_LABELS.get(col, col), "All indicators present"],
                             nodata_label="incomplete data: no index (never imputed)")
        maps.render(m, height=540)
    ui.source("DEP2 local run (C_vulnerability).")
    t1, t2, t3, t4 = st.tabs(["Indicators and weights", "Missing indicators", "Correlation", "Sensitivity and ranking"])
    with t1:
        d = R.csv("vuln_def")
        if d is not None:
            ui.table(d, height=230)
        st.json(R.js("vuln_weights", {}))
    with t2:
        d = R.csv("vuln_missing")
        if d is not None:
            ui.table(d, height=330)
    with t3:
        d = R.csv("vuln_corr")
        if d is not None:
            ui.table(d.round(2), height=200)
    with t4:
        d = R.csv("vuln_sens")
        if d is not None:
            ui.table(d.round(3), height=280)
            st.caption("Dropping one indicator moves the ranking substantially (ρ 0.56–0.85). The components are the primary output; the composite is exploratory.")
        r = R.csv("vuln_rank")
        if r is not None:
            ui.table(r.round(3), height=300)


def render_integrated():
    st.header("G. Integrated ward-level analysis")
    ui.badges("EXPLORATORY", "NOT VALIDATED")
    ui.note("The three dimensions are kept separate: relative susceptibility (SUS-1), exposure and partial vulnerability. Reported 2021 density is shown beside them. "
            "No combined risk score is computed, because there is no hazard layer, the reports are year-level presences and vulnerability is partial.")
    W = ward_table()
    if W is None:
        ui.missing(R.rel("wards_gpkg"))
        return
    d = W.drop(columns="geometry")
    c1, c2 = st.columns([3, 2])
    with c1:
        xs = {"sus_a_mean_pct": "SUS-1 mean percentile", "exposure_index_provisional": "exposure index (prov.)", "vulnerability_index_provisional": "vulnerability index (partial)",
              "reported_2021_per_km2": "CDMP 2021 records / km²", "population_density_cdmp_per_km2": "CDMP pop. density"}
        x = st.selectbox("x axis", list(xs), index=0, format_func=xs.get)
        y = st.selectbox("y axis", list(xs), index=1, format_func=xs.get)
        colour = st.selectbox("colour", list(xs), index=2, format_func=xs.get)
        ch = alt.Chart(d).mark_circle(opacity=0.8, stroke="#333", strokeWidth=0.3).encode(
            x=alt.X(f"{x}:Q", title=xs[x]), y=alt.Y(f"{y}:Q", title=xs[y]), color=alt.Color(f"{colour}:Q", title=xs[colour], scale=alt.Scale(scheme="orangered")),
            size=alt.Size("cdmp_records_2021:Q", title="CDMP 2021 records", scale=alt.Scale(range=[15, 260])),
            tooltip=["ward_no", "zone_no", alt.Tooltip(x, format=".2f"), alt.Tooltip(y, format=".2f"), alt.Tooltip(colour, format=".2f"), "cdmp_records_2021", "priority_profile_exploratory"]
        ).properties(height=420).interactive()
        ui.chart(ch)
        st.caption("Wards missing a value are omitted from the chart (2 wards lack CDMP population, so they have no vulnerability index). Marker size = number of CDMP 2021 records (0 = unlabelled).")
    with c2:
        corr = d[list(xs)].corr(method="spearman").round(2)
        st.markdown("**Spearman correlation**")
        ui.table(corr.reset_index().rename(columns={"index": "variable"}), height=230)
        st.markdown("**Missingness per dimension**")
        ui.table(pd.DataFrame({"variable": list(xs), "wards with value": [int(d[c].notna().sum()) for c in xs]}), height=230)
    st.subheader("Wards in the top tercile of all three (exploratory)")
    st.caption("Reported 2021 density, exposure and vulnerability. This profile is not a high-risk classification.")
    h = R.csv("high3")
    if h is not None:
        ui.table(h[["ward_no", "zone_no", "cdmp_records_2021", "reported_2021_per_km2", "exposure_index_provisional", "vulnerability_index_provisional"]].round(3), height=230)
    st.subheader("Top-tercile count map")
    W = W.copy()
    W["n_high"] = (W[["reported_2021_tercile", "exposure_tercile", "vulnerability_tercile"]] == "high").sum(axis=1).astype(float)
    W.loc[W.vulnerability_tercile == "not assessed", "n_high"] = np.nan
    m = maps.base_map()
    maps.ward_choropleth(m, W, "n_high", "Number of dimensions in top tercile (0–3)", cmap="OrRd", fields=["ward_no", "n_high", "priority_profile_exploratory"],
                         aliases=["Ward", "Top-tercile count", "reported/exposure/vulnerability"], nodata_label="not assessed")
    maps.render(m, height=520)
    with st.expander("Sensitivity of the components to normalisation and weighting"):
        s = R.csv("vuln_sens")
        if s is not None:
            ui.table(s.round(3), height=260)
        st.markdown("SUS-1 weighting sensitivity is recorded in the SUS-1 review (section D).")
    ui.cannot_claim("validated flood risk, a risk ranking of wards, or that any of the listed wards is at higher risk than another.")
