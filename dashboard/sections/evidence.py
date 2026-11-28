"""C. Flood-reference evidence."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from lib import maps, ui
from lib import registry as R
from lib.data import aoi, gpkg, wards


def render():
    st.header("C. Flood-reference evidence")
    ui.badges("REPORTED", "PRESENCE_ONLY", "QUALITATIVE_ONLY", "UNLABELLED")
    ui.note("Points and streets are <b>reported</b> flooding (administrative list or anonymous crowd flags). They are not flood extents. "
            "CDMP records carry the monsoon <b>year</b> only. A ward with no report is <b>unlabelled</b>, not flood-free.")
    W = wards()
    c1, c2 = st.columns([1, 3])
    with c1:
        show = st.multiselect("Evidence layers", ["CDMP 2021 locations", "CDMP 2015 locations", "Crowd-flagged streets 2 Dec 2015", "Ward reporting status 2021"],
                              default=["CDMP 2021 locations", "Ward reporting status 2021"])
        depth = st.multiselect("Depth class (verified against the PDF)", ["very_high", "high", "medium", "low", "unverified"],
                               default=["very_high", "high", "medium", "low", "unverified"])
    import folium
    m = maps.base_map()
    A = aoi()
    if A is not None:
        maps.add_aoi(m, A, "Study area (PROVISIONAL OSM AOI)")
    if "Ward reporting status 2021" in show and W is not None:
        g = W.copy()
        g["status_2021"] = np.where(g.cdmp_records_2021 > 0, "REPORTED (≥1 CDMP 2021 record)", "UNLABELLED (no listing; not flood-free)")
        folium.GeoJson(maps.display_geoms(g, ["ward_no", "cdmp_records_2021", "status_2021"]), name="Ward reporting status 2021",
                       style_function=lambda f: {"fillColor": "#f6ad55" if f["properties"]["status_2021"].startswith("REPORTED") else "#cbd2d9",
                                                 "color": "#718096", "weight": 0.4, "fillOpacity": 0.35 * maps.overlay_opacity(), "dashArray": None if f["properties"]["status_2021"].startswith("REPORTED") else "3 3"},
                       tooltip=folium.GeoJsonTooltip(fields=["ward_no", "cdmp_records_2021", "status_2021"], aliases=["Ward", "CDMP 2021 records", "Status"])).add_to(m)
    colours = {"very_high": "#67000d", "high": "#cb181d", "medium": "#fb6a4a", "low": "#fcbba1", "unverified": "#ffffff"}
    for yr, key, shape in ((2021, "cdmp_2021", "circle"), (2015, "cdmp_2015", "square")):
        if f"CDMP {yr} locations" in show:
            g = gpkg(key)
            if g is None:
                continue
            g = g.copy()
            g["depth"] = g.depth_class_verified.fillna("unverified")
            g = g[g.depth.isin(depth)]
            g["geometry"] = g.geometry.representative_point()
            fg = folium.FeatureGroup(name=f"CDMP {yr} reported locations (E3, year-level)")
            for r in g.to_crs("EPSG:4326").itertuples():
                tip = (f"<b>REPORTED (E3), GCC CDMP {yr}</b><br>{r.location}<br>ward {r.ward} · depth {r.depth}<br>"
                       f"placement: {r.placement_precision} (±{r.position_uncertainty_m:.0f} m)<br><i>a listed location, not a flood extent; year only</i>")
                if shape == "circle":
                    folium.CircleMarker([r.geometry.y, r.geometry.x], radius=4, color="#333", weight=0.6, fill=True, fill_color=colours[r.depth], fill_opacity=0.9, tooltip=tip).add_to(fg)
                else:  # 2015: thick dark ring (no plugin needed, works offline)
                    folium.CircleMarker([r.geometry.y, r.geometry.x], radius=5, color="#000", weight=2.2, fill=True, fill_color=colours[r.depth],
                                        fill_opacity=0.9, tooltip=tip).add_to(fg)
            fg.add_to(m)
    if "Crowd-flagged streets 2 Dec 2015" in show:
        o = gpkg("osmin_dec2")
        if o is not None:
            o = o[~o.outside_chennai_region & ~o.dup_osm_id]
            folium.GeoJson(maps.display_geoms(o, ["osm_id"]), name="Crowd-flagged flooded streets, 2 Dec 2015 11:00 IST (E3)",
                           style_function=lambda f: {"color": "#2171b5", "weight": 2},
                           tooltip="REPORTED (anonymous crowd flag, osm-in): street flagged as flooded by 2 Dec 2015 11:00 IST; not verified").add_to(m)
    maps.legend_html(m, "Evidence", [("#cb181d", "CDMP 2021 thin ring / 2015 thick ring (fill = depth class)"), ("#2171b5", "crowd-flagged street (2015)"),
                                     ("#f6ad55", "ward with ≥1 2021 report"), ("#cbd2d9", "UNLABELLED ward: no report, not flood-free")])
    with c2:
        maps.render(m)
    ui.source("GCC City Disaster Management Plan 2026 (depth classes re-verified against the PDF); placement: reclaimchennai gazetteer @56c3a6a; osm-in/flood-map @5790681 (ODbL); TNGIS wards.")

    t1, t2, t3, t4, t5 = st.tabs(["Evidence register", "Reference checker (R0–R2)", "Temporal alignment", "Comparisons and recurrence", "Chronology"])
    with t1:
        reg = R.csv("evidence_register")
        if reg is not None:
            st.markdown("Classes: **E1** mapped extent · **E2** georeferenced observation · **E3** reported · **E4** satellite candidate · **E5** context. "
                        "There is **no E1 item**.")
            ui.table(reg[["evidence_id", "source_name", "event", "observation_date", "evidence_class", "acquisition_status", "independence", "limitations"]], height=420)
        s = R.csv("cdmp_summary")
        if s is not None:
            st.markdown("**CDMP records per year** (placed = geolocated by the gazetteer; the rest are kept, unplaced)")
            ui.table(s, height=200)
    with t2:
        r = R.csv("r012")
        if r is not None:
            st.markdown("The project's own checker, run on the **project AOI** (local run `dep2_local_run_01`). These statuses are preserved exactly. "
                        "They are readiness classes, not accuracy results.")
            ui.table(r[["reference", "intake_status", "alignment_status", "primary_class", "candidate_label", "presence_only", "qualitative"]], height=160)
            with st.expander("Blockers per reference"):
                ui.table(r[["reference", "candidate_label_blockers", "presence_only_blockers"]], height=200)
    with t3:
        st.markdown("Sentinel-1A passes are at about **06:01 IST** (00:31 UTC), descending, relative orbit 92. CDMP records give only a year. "
                    "The checker's temporal 'PASS' for them is an artefact of the year-wide observation range (audit item CHK-03).")
        a = R.csv("s1_reassess")
        if a is not None:
            ui.table(a, height=320)
        b = R.csv("r1_2015")
        if b is not None:
            st.markdown("**2015 references vs 2015 Sentinel-1 dates** (checker's `temporal()` function)")
            ui.table(b, height=260)
    with t4:
        c = R.csv("cmp2015")
        if c is not None:
            st.markdown("**2015: CDMP vs crowd-flagged streets** (both reported, independent). Null = random points on the TNGIS street fabric.")
            ui.table(c.round(3), height=250)
        c = R.csv("cmp2021")
        if c is not None:
            st.markdown("**2021: CDMP (E3) vs S1PE bright-VV components (E4)**. Presence-only and exploratory.")
            ui.badges("CANDIDATE (E4)")
            ui.table(c.drop(columns=["comparison"], errors="ignore").round(3), height=320)
        rc = R.js("recurrence", {})
        if rc:
            st.markdown(f"**Recurrence:** {rc['wards_both']} wards are listed in both 2015 ({rc['wards_2015']}) and 2021 ({rc['wards_2021']}). "
                        f"{rc['same_name_same_ward_in_both']} exact location names recur. {rc['note']}")
    with t5:
        ch = R.csv("chronology")
        if ch is not None:
            ev = st.radio("Event", ["2021", "2015"], horizontal=True)
            ui.table(ch[ch.event.astype(str) == ev][["date_ist", "time_ist", "what", "kind", "source"]], height=420)
