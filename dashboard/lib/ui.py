"""Design system: one palette, evidence badges, notes and source lines used by every section."""
from __future__ import annotations

import streamlit as st

try:  # 'width="stretch"' replaced use_container_width in newer Streamlit; keep both working
    _V = tuple(int(x) for x in st.__version__.split(".")[:2])
except ValueError:  # pragma: no cover
    _V = (1, 30)
STRETCH = {"width": "stretch"} if _V >= (1, 46) else {"use_container_width": True}

PALETTE = {"ink": "#1f2933", "muted": "#52606d", "accent": "#1f4e79", "warn": "#b7791f", "bad": "#c0392b", "ok": "#1a7f37", "grey": "#9aa5b1"}

BADGES = {
    "REPORTED": ("#7b341e", "Reported observation (E3): an administrative or crowd report, not a mapped extent"),
    "PRESENCE_ONLY": ("#2c7a7b", "Presence-only: positives are usable; unreported units are unlabelled, never negative"),
    "QUALITATIVE_ONLY": ("#6b46c1", "Qualitative only: context, not for quantitative comparison"),
    "UNCERTAIN": ("#b7791f", "Uncertain: timing or location not resolvable from the source"),
    "UNLABELLED": ("#718096", "Unlabelled: no report; NOT confirmed flood-free"),
    "EXPLORATORY": ("#2b6cb0", "Exploratory derived product: not validated"),
    "NOT VALIDATED": ("#c0392b", "No independent validation exists for this layer"),
    "CANDIDATE (E4)": ("#2f855a", "Satellite-derived candidate: not confirmed floodwater"),
    "CONTEXT (E5)": ("#4a5568", "Context (e.g. rainfall): a driver, not flood occurrence"),
    "RETIRED": ("#000000", "Retired legacy product: kept for traceability only"),
}

CSS = """
<style>
/* FINAL-02: wider desktop canvas, self-contained contrast (dark text on light panels) so notes stay readable in
   Streamlit's light and dark themes; mobile keeps Streamlit's default padding. */
.block-container {padding-top: 1.2rem; max-width: min(1880px, 97vw); padding-left: 2.2rem; padding-right: 2.2rem;}
@media (max-width: 760px) { .block-container {padding-left: 1rem; padding-right: 1rem;} }
.badge {display:inline-block;color:#ffffff;padding:1px 8px;border-radius:10px;font-size:0.74rem;margin-right:4px;font-weight:700;letter-spacing:.02em}
.src {font-size:0.82rem;margin-top:-0.3rem;opacity:0.85}
.kpi {border:1px solid #cbd2d9;border-radius:8px;padding:10px 14px;background:#f5f7fa;color:#1f2933}
.kpi .v {font-size:1.45rem;font-weight:700;color:#102a43}
.kpi .l {font-size:0.82rem;color:#334e68}
.note {border-left:5px solid #b7791f;background:#fff4d6;color:#3d2a00;padding:9px 13px;margin:6px 0 12px 0;font-size:0.93rem;border-radius:0 6px 6px 0}
.note b, .note strong {color:#2a1d00}
.claim {border-left:5px solid #c0392b;background:#ffe9e7;color:#4a0f08;padding:9px 13px;margin:6px 0 12px 0;font-size:0.93rem;border-radius:0 6px 6px 0}
.claim b, .claim strong {color:#3a0a04}
.note a, .claim a {color:#0b4f8a;text-decoration:underline}
div[data-testid="stCaptionContainer"] {opacity: 0.92}
</style>
"""


def init():
    st.markdown(CSS, unsafe_allow_html=True)


def badge(name):
    col, tip = BADGES[name]
    return f"<span class='badge' style='background:{col}' title='{tip}'>{name}</span>"


def badges(*names):
    st.markdown(" ".join(badge(n) for n in names), unsafe_allow_html=True)


def source(text):
    st.markdown(f"<div class='src'>Source: {text}</div>", unsafe_allow_html=True)


def note(text):
    st.markdown(f"<div class='note'>{text}</div>", unsafe_allow_html=True)


def cannot_claim(text):
    st.markdown(f"<div class='claim'><b>Cannot be claimed:</b> {text}</div>", unsafe_allow_html=True)


def kpis(items):
    cols = st.columns(len(items))
    for c, (label, value) in zip(cols, items):
        c.markdown(f"<div class='kpi'><div class='v'>{value}</div><div class='l'>{label}</div></div>", unsafe_allow_html=True)


def missing(path):
    st.warning(f"Not available in this checkout: `{path}`. Nothing is shown in its place.")


def table(df, height=280, **kw):
    st.dataframe(df, height=height, hide_index=True, **STRETCH, **kw)


def chart(c):
    st.altair_chart(c, **STRETCH)


def guard_text(summary: dict) -> tuple[str, str]:
    """Precise integrity wording from a run summary: ('4 guarded inputs unchanged', tooltip listing the files).
    The count comes from the recorded input_hashes, never a constant."""
    hashes = summary.get("input_hashes") or {}
    n = len(hashes)
    names = ", ".join(str(k).replace("\\", "/").rsplit("/", 1)[-1] for k in hashes)
    flag = summary.get("inputs_unchanged")
    if n == 0:
        return "no input guard recorded", ""
    if flag is True:
        return f"{n} guarded input{'s' if n != 1 else ''} unchanged", f"Hash-checked before and after the run: {names}. Other inputs were not hash-guarded."
    return f"{n} guarded input{'s' if n != 1 else ''}: CHANGED during run", f"Hash guard failed for: {names}"
