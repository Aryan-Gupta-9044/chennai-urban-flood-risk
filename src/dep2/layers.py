"""Loaders for the acquired DEP-2 source layers (read-only; originals are never modified)."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ANALYSIS_CRS, GEO_CRS, LOG


class Sources:
    """Paths of the acquired originals, relative to data/external/dep2_sources."""

    def __init__(self, raw_root: Path):
        r = Path(raw_root)
        self.root = r
        rc = r / "reclaimchennai"
        self.cdmp_pdf = r / "gcc_cdmp/cdmp_2026.pdf"
        self.cdmp_pdf_2024 = r / "gcc_cdmp/cdmp_2024.pdf"
        self.history = rc / "data/cdmp/2026/datasets/inundation_history.csv"
        self.history_2024 = rc / "data/cdmp/2024/datasets/inundation_history.csv"
        self.population_csv = rc / "data/cdmp/2026/datasets/population.csv"
        self.relief_csv = rc / "data/cdmp/2026/datasets/relief_centres.csv"
        self.flood_spots = rc / "data/layers/flood_spots.geojson"
        self.relief_layer = rc / "data/layers/relief.geojson"
        self.tngis = rc / "raw/tngis"
        self.osm = rc / "raw/osm"
        self.osmin_dec2 = r / "osm_in_flood_map/data/chennai-flooded-streets-Dec2.geojson"
        self.osmin_dec31 = r / "osm_in_flood_map/data/chennai-flooded-streets-Dec31.geojson"
        self.worldpop = r / "km658/input/chennai_pop_2020_100m.tif"
        self.slums = r / "km658/input/slum_boundary_shapefile/output.shp"
        self.datameet_wards = r / "datameet/Chennai/Wards.geojson"


def read_gz_geojson(p: Path, crs=GEO_CRS):
    import geopandas as gpd
    with gzip.open(p, "rt", encoding="utf-8") as f:
        j = json.load(f)
    feats = j.get("features", [])
    g = gpd.GeoDataFrame.from_features(feats, crs=crs) if feats else gpd.GeoDataFrame(geometry=[], crs=crs)
    g.attrs["source"] = j.get("source")
    return g


def _valid(g):
    from shapely import make_valid
    if g is None or g.is_valid:
        return g
    try:
        return make_valid(g, method="structure")
    except Exception:  # noqa: BLE001  (GEOS mixed-dimension input)
        return g.buffer(0)


def load_wards(src: Sources):
    """TNGIS GCC ward boundary (200 wards, current delimitation) in EPSG:32644, geometries made valid."""
    w = read_gz_geojson(src.tngis / "gcc_ward_boundary.geojson.gz")
    n_invalid = int((~w.is_valid).sum())
    w["geometry"] = [_valid(g) for g in w.geometry]
    w = w.explode(index_parts=False)
    w = w[w.geom_type.isin(["Polygon", "MultiPolygon"])].dissolve(by="ward", as_index=False, aggfunc="first")
    w["ward_no"] = w["ward"].astype(int)
    w["zone_no"] = w["zone"].astype(int)
    w = w.to_crs(ANALYSIS_CRS).sort_values("ward_no").reset_index(drop=True)
    w["area_km2"] = w.area / 1e6
    w.attrs["n_invalid_repaired"] = n_invalid
    LOG.info("wards: %d (%d invalid geometries repaired with make_valid), %.2f km2", len(w), n_invalid, w.area_km2.sum())
    return w[["ward_no", "zone_no", "zone_label", "region", "area_km2", "geometry"]]


_INT = re.compile(r"\d{1,3}")


def _num(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    s = str(v).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return np.nan


def ward_population(src: Sources, wards) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ward population and households as printed in the GCC CDMP 2026 zone chapters.

    Parsed from the third-party table extraction, then validated per zone against the printed
    zone TOTAL row and against the TNGIS ward list. Zones that fail validation are reported and
    their wards set to NaN (never imputed). The reference year of these figures is NOT stated in
    the tables; they must not be called census counts.
    """
    p = pd.read_csv(src.population_csv, dtype=str)
    zw = wards.groupby("zone_no").ward_no.apply(lambda s: sorted(s)).to_dict()
    rows, checks = [], []
    for z, g in p.groupby(p.zone.astype(int)):
        g = g.dropna(axis=1, how="all")
        cols = [c for c in g.columns if c not in ("zone", "pdf_page", "table_id", "kind", "caption")]
        hh_c = next((c for c in cols if "House" in c), None)
        pop_c = next((c for c in cols if "Population" in c), None)
        ward_c = next((c for c in cols if c.startswith("Ward")), None)
        sl_c = next((c for c in cols if c.replace(" ", "").lower().startswith("sl")), None)
        merged = hh_c is not None and "Ward" in hh_c          # zone 3 layout: ward/name and households merged in one cell
        zone_rows, total = [], None
        for _, r in g.iterrows():
            texts = " ".join(str(r[c]) for c in cols if isinstance(r[c], str))
            last = lambda c: (str(r.get(c, "")).split() or [None])[-1]  # noqa: E731  (zone 8: rows repeated with shifted cells)
            if "total" in texts.lower():
                total = (_num(last(hh_c) if not merged else None), _num(last(pop_c)))
                continue
            wtxt = (str(r.get("col2", "")) + " " + str(r.get(hh_c, ""))) if merged else str(r.get(ward_c, ""))
            cand = [int(x) for x in _INT.findall(wtxt) if int(x) in zw.get(z, [])]
            ward = cand[-1] if cand else None
            if ward is None and z == 1:
                sv = _num(r.get(sl_c))
                ward = int(sv) if sv == sv and int(sv) in zw[z] else None
            hh = _num(last(hh_c)) if hh_c else np.nan
            if merged:
                hh = _num(str(r.get(hh_c, "")).split()[-1]) if str(r.get(hh_c, "")).split() else np.nan
            pop = _num(last(pop_c))
            zone_rows.append({"zone_no": z, "ward_no": ward, "households": hh, "population": pop, "row_text": texts[:120]})
        zr = pd.DataFrame(zone_rows).drop_duplicates(subset=["ward_no", "households", "population"])
        dup = zr.ward_no.duplicated(keep=False) & zr.ward_no.notna()
        ambiguous = sorted(set(zr.ward_no[dup].astype(int)))
        pop_sum = float(zr.population.sum())
        tot = None if total is None else total[1]
        rel = None if not tot else abs(pop_sum - tot) / tot
        zr = zr[~dup & zr.ward_no.notna()]
        missing = sorted(set(zw.get(z, [])) - set(zr.ward_no.astype(int)))
        ok_total = rel is not None and rel <= 0.02
        checks.append({"zone_no": z, "rows_parsed": len(zone_rows), "tngis_wards": len(zw.get(z, [])), "wards_without_value": ",".join(map(str, missing)),
                       "ambiguous_duplicate_ward_numbers": ",".join(map(str, ambiguous)), "sum_population_rows": pop_sum,
                       "printed_total_population": tot, "relative_difference": rel,
                       "printed_total_consistent": bool(rel is not None and rel < 1e-6),
                       "accepted": bool(ok_total), "note": "" if rel is not None and rel < 1e-6 else ("printed zone total differs from the sum of its rows (source arithmetic); rows kept" if ok_total else "REJECTED: rows do not reconcile with the printed total")})
        if ok_total:
            rows.append(zr)
    chk = pd.DataFrame(checks)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["zone_no", "ward_no", "households", "population"])
    out["ward_no"] = out.ward_no.astype(int)
    LOG.info("CDMP ward population: %d zones accepted of %d; %d wards", int(chk.accepted.sum()), len(chk), len(out))
    return out[["ward_no", "zone_no", "households", "population"]], chk
