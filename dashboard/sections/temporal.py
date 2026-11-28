"""H. Rainfall and temporal analysis; I. Sentinel-1 analysis."""
from __future__ import annotations

import altair as alt
import pandas as pd
import numpy as np
import streamlit as st

from lib import maps, ui
from lib import registry as R
from lib.data import aoi


def _rule(dates, colour="#2b6cb0"):
    return alt.Chart(pd.DataFrame({"date": pd.to_datetime(dates)})).mark_rule(color=colour, strokeDash=[3, 3]).encode(x="date:T")


def render_rainfall():
    st.header("H. Rainfall and temporal analysis")
    ui.badges("CONTEXT (E5)")
    ui.note("Rainfall is a <b>driver</b>, not flood occurrence. CHIRPS v3 (0.05°, about 29 native cells over the AOI) carries no sub-5 km detail. "
            "Its <b>day definition is provisional</b>: the local-IST observation window is unverified. "
            "The IMD 0.25° comparison is <b>side by side, not validation</b>: only 1 of 3 IMD cells is valid over the AOI.")
    ev = st.radio("Event window", ["2021 Sep–Nov (CHIRPS v3)", "2015 Jul–Dec (CHIRPS v3 + IMD)"], horizontal=True)
    if ev.startswith("2021"):
        s, ante, mk, s1 = R.csv("chirps21"), R.csv("chirps21_ante"), R.csv("chirps21_maxk"), R.S1_DATES
    else:
        s, ante, mk, s1 = R.csv("chirps15"), R.csv("chirps15_ante"), R.csv("chirps15_maxk"), ["2015-11-12", "2015-11-24", "2015-12-06", "2015-12-18"]
    if s is not None:
        s = s.assign(date=pd.to_datetime(s.date))
        bars = alt.Chart(s).mark_bar(color="#4292c6").encode(x=alt.X("date:T", title="date (CHIRPS day; definition provisional)"),
                                                             y=alt.Y("aoi_mean_mm:Q", title="AOI mean rainfall (mm/day)"),
                                                             tooltip=["date:T", alt.Tooltip("aoi_mean_mm:Q", format=".1f"), alt.Tooltip("aoi_max_mm:Q", format=".1f"), "status"])
        ui.chart((bars + _rule(s1)).properties(height=300))
        st.caption("Dashed lines: Sentinel-1 acquisition dates (about 06:01 IST). Event total, wettest day and k-day maxima are in the tables below.")
        st.markdown(f"**Event total (AOI mean):** {s.aoi_mean_mm.sum():.0f} mm over {len(s)} days. **Wettest day:** {s.loc[s.aoi_mean_mm.idxmax(), 'date'].date()} "
                    f"({s.aoi_mean_mm.max():.0f} mm AOI mean).")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Antecedent rainfall before each Sentinel-1 date**")
        if ante is not None:
            ui.table(ante.round(1), height=300)
    with c2:
        st.markdown("**Maximum k-day totals**")
        if mk is not None:
            ui.table(mk.round(1), height=300)
    if ev.startswith("2015"):
        imd = R.csv("imd_cmp")
        if imd is not None:
            st.subheader("CHIRPS vs IMD, 2015 (side by side, not validation)")
            imd = imd.assign(date=pd.to_datetime(imd.date)).melt(id_vars="date", value_vars=["chirps_aoi_mean_mm", "imd_r101c55_mm", "chirps_footprint_r101c55_mm"],
                                                                 var_name="series", value_name="mm")
            ui.chart(alt.Chart(imd).mark_line().encode(x="date:T", y="mm:Q", color="series:N").properties(height=260))
            sup = R.csv("imd_support")
            if sup is not None:
                ui.table(sup, height=160)
    ui.source("outputs/chirps_2021, outputs/tables (CHIRPS v3 2015), outputs/cmp_chirps_imd_run_20261128_01.")


def render_sentinel1():
    st.header("I. Sentinel-1 analysis (2021)")
    ui.badges("CANDIDATE (E4)", "EXPLORATORY")
    ui.note("Three kinds of product must be kept apart:\n"
            "<ul style='margin:0.3rem 0 0.3rem 1.2rem;padding:0'>"
            "<li><b>Radar observations</b> (VV/VH backscatter, dB).</li>"
            "<li><b>Water-signature candidates</b> (S1WC-2 class 1: dark on a date, not floodwater; class 8: dark on the provisional DEM flattened-water signature, not confirmed permanent water).</li>"
            "<li><b>Confirmed flood extent</b>, which this project does not have.</li>"
            "</ul>"
            "Date-level radiometric offsets make fixed-threshold counts non-comparable across dates.")
    c1, c2 = st.columns([1, 3])
    with c1:
        date = st.selectbox("Acquisition (UTC date; ~06:01 IST)", R.S1_DATES, index=7)
        layer = st.radio("Layer", ["S1WC-2 class (candidates)", "VV backscatter (dB)", "VH backscatter (dB)", "Class-1 candidate date count (all dates)", "Bright-VV frequency (> +5 dB)"])
    m = maps.base_map()
    A = aoi()
    if A is not None:
        maps.add_aoi(m, A, "Study area (PROVISIONAL OSM AOI)")
    if layer.startswith("S1WC-2"):
        p = R.s1_class_raster(date)
        # every drawn class is in the legend (FINAL-02: classes 2-5 were drawn but not explained)
        cats = {1: ("#08519c", "1: transient dark candidate (E4, not floodwater)"), 8: ("#9e9ac8", "8: dark on provisional DEM flat-water signature"),
                2: ("#fdae6b", "2: persistently dark (excluded; permanent-water-like)"), 3: ("#e6550d", "3: dark, excluded: slope above limit"),
                4: ("#fd8d3c", "4: dark, excluded: cluster below minimum size"), 5: ("#a1d99b", "5: VV dark only (weak; not a candidate)"),
                6: ("#74c476", "6: dark, persistence not assessable"), 7: ("#31a354", "7: dark, slope unknown"),
                254: ("#bdbdbd", "254: invalid / no data inside AOI"), 0: ("none", "0: valid, not dark (NOT 'no flood')")}
        if p.is_file():
            import rasterio
            with rasterio.open(p) as ds:
                present = set(int(x) for x in np.unique(ds.read(1)))
            maps.add_raster(m, p, f"S1WC-2 class {date}", show=True, categorical=cats)
            maps.legend_html(m, f"S1WC-2 classes, {date} (only classes present on this date)",
                             [(c, lab) for k, (c, lab) in cats.items() if k in present and c != "none"] + [("transparent", "0: valid, not dark — NOT 'no flood' (transparent)")])
    elif layer.startswith("VV") or layer.startswith("VH"):
        p = R.s1_vv(date, "VV" if layer.startswith("VV") else "VH")
        if p.is_file():
            maps.add_raster(m, p, f"{layer} {date}", show=True, cmap="gray", vmin=-25 if layer.startswith("VV") else -30, vmax=5 if layer.startswith("VV") else -5)
    elif layer.startswith("Class-1"):
        maps.add_raster(m, R.P["s1wc2_count_raster"], layer, show=True, cmap="Blues", vmin=0, vmax=8)
    else:
        if R.exists("s1pe_freq"):
            maps.add_raster(m, R.P["s1pe_freq"], layer, show=True, cmap="Oranges", vmin=0, vmax=1)
    with c2:
        maps.render(m)
    st.caption(maps.CRS_NOTE + " Sentinel-1A IW GRD, descending, relative orbit 92.")
    t0, t1, t2, t3, t4 = st.tabs(["Multi-date context (S1TC-1)", "Preprocessing QA", "Date-level coverage", "Candidate counts (S1WC-2)", "High-VV diagnostics (S1PE)"])
    with t0:
        _s1_temporal_context()
    with t1:
        q = R.csv("s1_qa")
        if q is not None:
            ui.table(q[[c for c in ["date_utc", "pol", "status", "failures", "aoi_cells", "aoi_valid_cells", "aoi_valid_pct", "nodata_cells_in_aoi"] if c in q]], height=320)
    with t2:
        q = R.csv("s1_cov")
        if q is not None:
            ui.table(q.iloc[:, :12], height=300)
    with t3:
        q = R.csv("s1wc2_before_after")
        if q is not None:
            ui.table(q, height=300)
        q = R.csv("s1wc2_comparability")
        if q is not None:
            with st.expander("Per-date comparability (radiometric offsets)"):
                ui.table(q.round(3), height=300)
    with t4:
        q = R.csv("s1pe_class_counts")
        if q is not None:
            ui.table(q, height=240)
        st.markdown("Against the CDMP 2021 reports (section C), bright-VV components show no association beyond a street-fabric null at 0–100 m.")
    ui.source("data/processed/s1_2021 (S1WC-2 preprocessing, Earth Engine COPERNICUS/S1_GRD); outputs/s1_water_candidates_review_v2; outputs/s1_2021_persistence_v1_2.")


def _s1_temporal_context():
    """FINAL-02: how class-1 candidates vary across the eight dates (outputs/s1_temporal_context_v1)."""
    ui.badges("CANDIDATE (E4)", "CONTEXT (E5)", "EXPLORATORY")
    if not R.exists("s1tc_per_date"):
        ui.missing(R.rel("s1tc_per_date"))
        st.code(".\\.venv\\Scripts\\python.exe scripts\\build_s1_temporal_context.py")
        return
    s = R.js("s1tc_summary", {})
    d = R.csv("s1tc_per_date")
    ui.kpis([("class-1 area per date (km²)", f"{d.class1_km2.min():.2f}–{d.class1_km2.max():.2f}"),
             ("median date-to-date overlap (Jaccard)", f"{s.get('jaccard_offdiag_median', float('nan')):.2f}"),
             ("ever-candidate cells seen on 1 date only", f"{100 * s.get('class1_on_1_date_share', float('nan')):.0f}%"),
             ("enrichment in SUS-1 top decile (median)", f"{s.get('top_decile_enrichment_median', float('nan')):.1f}×")])
    ui.note("Class-1 candidates are small (well under 0.5% of the AOI on every date), change location from date to date, and sit mostly in the "
            "highest SUS-1 deciles. That is <b>internal consistency</b> between a terrain index and a radar signal, not validation: both use DEM slope "
            "(SUS-1 as an indicator, S1WC-2 as a screen), and no flood reference exists for any of these dates. On 28 Nov 2021, after about 250 mm of "
            "CHIRPS rainfall in the prior 7 days, the class-1 area was still only about 1.2 km²: dark-water detection does not capture urban street flooding.")
    if R.exists("s1tc_fig"):
        st.image(str(R.P["s1tc_fig"]), caption="Left: class-1 area per date with CHIRPS prior-7-day mean (E5). Middle: Jaccard overlap between dates. "
                 "Right: share of class-1 cells per SUS-1 decile relative to the decile's share of scored cells (1 = no enrichment).")
    c1, c2 = st.columns(2)
    with c1:
        ui.table(d[["date", "class1_km2", "class8_km2", "class1_mean_sus1_pct", "class1_share_in_sus1_top_decile", "wards_with_any_class1",
                    "top10_ward_share", "prior_3d_aoi_mean_mm", "prior_7d_aoi_mean_mm"]], height=330)
    with c2:
        r = R.csv("s1tc_rain")
        if r is not None:
            st.markdown("**Rainfall context** (Spearman over 8 dates; descriptive, not causal)")
            ui.table(r[["rainfall", "n_dates", "spearman_rho", "p_naive"]], height=200)
        p = R.csv("s1tc_persist")
        if p is not None:
            st.markdown("**Persistence**: on how many of the 8 dates a cell was class 1 (class 1 excludes persistently dark cells by design)")
            ui.table(p, height=200)
    ui.source("outputs/s1_temporal_context_v1 (scripts/build_s1_temporal_context.py; inputs hash-guarded: S1WC-2 rasters, SUS-1 rasters, CHIRPS table).")
