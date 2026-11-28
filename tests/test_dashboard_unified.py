"""Unified dashboard: every section renders headlessly; scientific framing and legacy handling are enforced."""
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app.py"
sys.path.insert(0, str(ROOT / "dashboard"))

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

SECTIONS = ["A. Overview", "B. Study area", "C. Flood-reference evidence", "D. Susceptibility (SUS-1)", "E. Exposure", "F. Vulnerability",
            "G. Integrated wards", "H. Rainfall and time", "I. Sentinel-1", "J. ML and analytics", "K. Data quality and reproducibility"]


@pytest.mark.parametrize("section", SECTIONS)
def test_section_renders_without_exception(section):
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.session_state["section"] = section
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def _text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [w.value for w in at.warning] + [i.value for i in at.info]
    return " ".join(str(p) for p in parts)


def test_overview_states_what_cannot_be_claimed():
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    txt = _text(at)
    assert "Cannot be claimed" in txt and "not the official GCC boundary" in txt.replace("**", "") or "PROVISIONAL" in txt
    assert "flood probability" in txt


def test_evidence_section_never_calls_unreported_wards_flood_free():
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.session_state["section"] = "C. Flood-reference evidence"
    at.run()
    txt = _text(at)
    assert "unlabelled" in txt.lower() and "not flood-free" in txt


def test_legacy_rf_is_not_a_map_layer():
    for p in (ROOT / "dashboard").rglob("*.py"):
        if "legacy" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        assert "Flood susceptibility (RF v0)" not in src, p
    assert "RETIRED" in (ROOT / "dashboard/sections/ml_quality.py").read_text(encoding="utf-8")


def test_original_dashboard_preserved_verbatim():
    p = ROOT / "dashboard/legacy/app_v0_initial.py"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == "ecda30d85a4c07513478ffc2c7790a13a16e896950f60e17e6d9885db4f9b8cd"


def test_registry_paths_are_inside_repository():
    from lib import registry as R
    for k, p in R.P.items():
        assert R.ROOT in p.resolve().parents, k
