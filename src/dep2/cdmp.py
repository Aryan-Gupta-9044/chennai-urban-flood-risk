"""GCC City Disaster Management Plan (CDMP) inundation records -> verified, located E3 evidence.

Inputs (all acquired originals, SHA-256 verified):
* the official CDMP 2026 PDF (Greater Chennai Corporation);
* a third-party table extraction of it (reclaimchennai, commit 56c3a6a) - `inundation_history.csv`;
* the same project's gazetteer placement of each location (`flood_spots.geojson`), which
  locates printed street/place names inside their own ward using TNGIS and OSM.

The depth class of every record is RE-VERIFIED against the PDF here. The third-party extraction
was found to shift depth-class columns (e.g. the 3-5 ft "High" column is lost in 2015 and
labelled "very_high" in 2021). Each page is re-read: the "Yes" marks are assigned to the depth
column whose rotated header is nearest, in reading order, and attached to the rows in their
printed order *only when the counts agree*; otherwise the record is flagged UNVERIFIED.
Temporal resolution of the source is the monsoon YEAR only (no dates).
"""
from __future__ import annotations

import collections
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ANALYSIS_CRS, LOG

DEPTH_LABELS = {"very_high": "> 5 ft", "high": "3-5 ft", "medium": "2-3 ft", "low": "< 2 ft"}
_HEADER_KEYS = (("Very High", "very_high"), ("High", "high"), ("Medium", "medium"), ("Low", "low"), ("Status", "status"))

# positional uncertainty radius (m) assigned by placement precision (documented assumption)
PRECISION_RADIUS_M = {"street": 50.0, "place": 100.0, "office": 300.0, "locality": 750.0}


def _page_columns(page):
    cols = collections.defaultdict(list)
    for c in page.chars:
        if not c.get("upright", True) and c["top"] < 200:
            cols[round(c["x0"] / 6)].append(c)
    anchors = {}
    for k in sorted(cols):
        s = "".join(c["text"] for c in sorted(cols[k], key=lambda c: -c["top"])).strip()
        for key, lab in _HEADER_KEYS:
            if s.startswith(key) and lab not in anchors and not (key == "High" and s.startswith("Very")):
                anchors[lab] = k * 6
    return anchors


def verify_depth_classes(history: pd.DataFrame, pdf_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (records with verified depth class, page-level reconciliation table)."""
    import pdfplumber

    h = history.copy().reset_index(drop=True)
    h["row_id"] = np.arange(len(h))
    h["depth_class_extracted"] = h["depth_class"]
    h["depth_class_verified"] = pd.NA
    h["status_verified"] = pd.NA
    h["depth_verification"] = "UNVERIFIED"
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for pn in sorted(h.pdf_page.unique()):
            page = pdf.pages[int(pn) - 1]
            anchors = _page_columns(page)
            depth_anchors = {k: v for k, v in anchors.items() if k != "status"}
            yes = sorted((w for w in page.extract_words() if w["text"] == "Yes"), key=lambda w: (round(w["top"]), w["x0"]))
            depth_marks, status_marks = [], []
            for w in yes:
                xc = (w["x0"] + w["x1"]) / 2
                if not anchors:
                    continue
                lab = min(anchors, key=lambda l: abs(anchors[l] + 6 - xc))
                (status_marks if lab == "status" else depth_marks).append((w["top"], lab))
            idx = h.index[h.pdf_page == pn].tolist()
            ok = bool(depth_anchors) and len(depth_marks) == len(idx)
            if ok:
                for i, (_, lab) in zip(idx, depth_marks):
                    h.at[i, "depth_class_verified"] = lab
                    h.at[i, "depth_verification"] = "VERIFIED_AGAINST_PDF"
            cnt_pdf = collections.Counter(l for _, l in depth_marks)
            cnt_ext = h.loc[idx, "depth_class_extracted"].fillna("missing").value_counts().to_dict()
            pages.append({"pdf_page": int(pn), "year": int(h.loc[idx[0], "year"]), "rows_extracted": len(idx),
                          "pdf_depth_marks": len(depth_marks), "pdf_status_marks": len(status_marks),
                          "pdf_counts": dict(cnt_pdf), "extracted_counts": cnt_ext,
                          "header_columns_found": ",".join(anchors), "row_level_verified": ok})
    h["depth_class_label"] = h["depth_class_verified"].map(DEPTH_LABELS)
    h["extraction_agrees"] = np.where(h.depth_verification == "VERIFIED_AGAINST_PDF",
                                      h.depth_class_extracted.fillna("missing") == h.depth_class_verified.fillna("x"), pd.NA)
    rec = pd.DataFrame(pages)
    LOG.info("CDMP depth classes: %d/%d rows verified against the PDF; %d pages fully reconciled of %d",
             int((h.depth_verification == "VERIFIED_AGAINST_PDF").sum()), len(h), int(rec.row_level_verified.sum()), len(rec))
    return h, rec


def locate_records(records: pd.DataFrame, flood_spots_path: Path, wards_gdf=None):
    """Attach the gazetteer geometry (if any) to each (year, ward, location) record.

    Returns a GeoDataFrame in EPSG:32644 with one row per record. Records that the gazetteer
    did not place keep an empty geometry and `placed=False` (never dropped, never guessed).
    """
    import geopandas as gpd
    from shapely.ops import unary_union

    fs = gpd.read_file(flood_spots_path)
    fs = fs.to_crs(ANALYSIS_CRS)
    fs["ward_key"] = pd.to_numeric(fs["ward"], errors="coerce")
    fs["name_key"] = fs["name"].astype(str).str.strip().str.lower()
    fs["years_list"] = fs["years"].apply(lambda v: [int(x) for x in (list(v) if v is not None else [])])
    groups = {}
    for (nk, wk), g in fs.groupby(["name_key", "ward_key"], dropna=False):
        parts = [x if x.is_valid else x.buffer(0) if x.geom_type in ("Polygon", "MultiPolygon") else x for x in g.geometry if x is not None and not x.is_empty]
        geom = unary_union(parts)
        if not geom.is_valid:
            from shapely import make_valid
            geom = make_valid(geom, method="structure")
        yrs = sorted({y for L in g.years_list for y in L})
        groups[(nk, wk)] = (geom, g["prec"].iloc[0], g["src"].iloc[0], g["match"].iloc[0], yrs)
    r = records.copy()
    r["name_key"] = r["location"].astype(str).str.strip().str.lower()
    r["ward_key"] = pd.to_numeric(r["ward"], errors="coerce")
    geoms, prec, src, match, yr_ok = [], [], [], [], []
    for nk, wk, yr in zip(r.name_key, r.ward_key, r.year):
        g = groups.get((nk, wk))
        if g is None:
            geoms.append(None); prec.append("unplaced"); src.append(None); match.append(None); yr_ok.append(False)
        else:
            geoms.append(g[0]); prec.append(g[1]); src.append(g[2]); match.append(g[3]); yr_ok.append(int(yr) in g[4])
    gdf = gpd.GeoDataFrame(r.drop(columns=["name_key", "ward_key"]), geometry=geoms, crs=ANALYSIS_CRS)
    gdf["placement_precision"] = prec
    gdf["placement_source"] = src
    gdf["placement_match"] = match
    gdf["placement_year_consistent"] = yr_ok
    gdf["placed"] = gdf.geometry.notna() & ~gdf.geometry.is_empty if len(gdf) else []
    gdf["position_uncertainty_m"] = gdf.placement_precision.map(PRECISION_RADIUS_M)
    gdf["evidence_class"] = "E3"
    gdf["temporal_resolution"] = "monsoon year (no date in source)"
    gdf["observation_type"] = "REPORTED (administrative list, GCC CDMP)"
    LOG.info("CDMP records placed: %d/%d", int(gdf.placed.sum()), len(gdf))
    return gdf
