"""Chennai urban flood-risk research dashboard (unified, v1).

Extends the initial foundation dashboard (preserved verbatim at dashboard/legacy/app_v0_initial.py) into one
research application with sections A-K. Every view reads files the pipelines generated (registry in
dashboard/lib/registry.py); nothing is shown that was not produced, and missing inputs are reported as missing.

Run:  .\\.venv\\Scripts\\streamlit.exe run dashboard\\app.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Chennai Flood Risk - B794 research dashboard", layout="wide", page_icon=":ocean:")

from lib import ui  # noqa: E402
from sections import analysis, evidence, ml_quality, overview, temporal  # noqa: E402

SECTIONS = {
    "A. Overview": overview.render_overview,
    "B. Study area": overview.render_study_area,
    "C. Flood-reference evidence": evidence.render,
    "D. Susceptibility (SUS-1)": analysis.render_susceptibility,
    "E. Exposure": analysis.render_exposure,
    "F. Vulnerability": analysis.render_vulnerability,
    "G. Integrated wards": analysis.render_integrated,
    "H. Rainfall and time": temporal.render_rainfall,
    "I. Sentinel-1": temporal.render_sentinel1,
    "J. ML and analytics": ml_quality.render_ml,
    "K. Data quality and reproducibility": ml_quality.render_quality,
}

ui.init()
with st.sidebar:
    st.markdown("### Chennai urban flood-risk\nIntegrated geospatial framework · B794")
    choice = st.radio("Section", list(SECTIONS), key="section")
    st.markdown("---")
    st.slider("Map overlay opacity", 0.2, 1.0, 1.0, 0.1, key="ov_opacity",
              help="Scales the opacity of thematic overlays on every map (rasters and ward polygons). Basemap and outlines are unaffected.")
    st.markdown("**Evidence legend**")
    st.markdown("<br>".join(ui.badge(b) for b in ("REPORTED", "PRESENCE_ONLY", "QUALITATIVE_ONLY", "UNLABELLED", "CANDIDATE (E4)", "CONTEXT (E5)", "EXPLORATORY", "NOT VALIDATED")),
                unsafe_allow_html=True)
    st.caption("Nothing here is a validated flood prediction, hazard or risk map. "
               "The study area is a provisional OSM-derived boundary, not the official GCC boundary.")

SECTIONS[choice]()
