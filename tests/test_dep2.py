"""DEP-2 tests: unit tests on synthetic data + real-data smoke tests (skipped when the acquired sources are absent)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd  # noqa: E402
from shapely.geometry import LineString, Point, box  # noqa: E402

from dep2 import acquire, cdmp, common, exposure, layers, mlcontract, reference, vulnerability  # noqa: E402

RAW = ROOT / "data" / "external" / "dep2_sources"
OUT = ROOT / "outputs" / "dep2_reference_exposure_vulnerability_2026"
real = pytest.mark.skipif(not (RAW / "gcc_cdmp" / "cdmp_2026.pdf").is_file(), reason="acquired sources not present")
CRS = common.ANALYSIS_CRS


# --------------------------------------------------------------------------- acquisition / protection
def _manifest(tmp, content=b"hello"):
    src = tmp / "cache"
    src.mkdir()
    (src / "a.txt").write_bytes(content)
    m = {"files": [{"source_id": "T", "url": "http://invalid.example/a.txt", "dest": "x/a.txt", "sha256": common.sha256_file(src / "a.txt")}], "release_assets": []}
    (tmp / "m.json").write_text(json.dumps(m))
    return src


def test_acquire_from_verified_cache_and_log(tmp_path):
    cache = _manifest(tmp_path)
    log = acquire.acquire(tmp_path / "m.json", tmp_path / "raw", cache_dirs=[cache])
    assert log["all_hashes_verified"] and (tmp_path / "raw/x/a.txt").read_bytes() == b"hello"


def test_acquire_stops_if_original_was_modified(tmp_path):
    cache = _manifest(tmp_path)
    acquire.acquire(tmp_path / "m.json", tmp_path / "raw", cache_dirs=[cache])
    p = tmp_path / "raw/x/a.txt"
    p.chmod(0o644)
    p.write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="immutable"):
        acquire.acquire(tmp_path / "m.json", tmp_path / "raw", cache_dirs=[cache])


def test_acquire_rejects_wrong_cache_hash(tmp_path):
    cache = _manifest(tmp_path)
    (cache / "a.txt").write_bytes(b"other")
    with pytest.raises(Exception):  # cache refused -> download attempted -> fails (no network to invalid host)
        acquire.acquire(tmp_path / "m.json", tmp_path / "raw", cache_dirs=[cache])
    assert not (tmp_path / "raw/x/a.txt").exists()


@pytest.mark.parametrize("out", ["outputs/susceptibility_v1", "outputs/susceptibility_v1/x", "outputs"])
def test_guard_refuses_protected_overlap(tmp_path, out):
    with pytest.raises(SystemExit):
        common.guard_output_dir(tmp_path / out, [tmp_path / "outputs/susceptibility_v1"])


def test_guard_allows_new_versioned_dir(tmp_path):
    common.guard_output_dir(tmp_path / "outputs/dep2_x", [tmp_path / "outputs/susceptibility_v1"])


# --------------------------------------------------------------------------- CDMP placement
def test_locate_records_keeps_unplaced_and_never_guesses(tmp_path):
    fs = gpd.GeoDataFrame({"name": ["Anna Road"], "ward": [5.0], "years": [[2021]], "prec": ["street"], "src": ["TNGIS"], "match": ["Anna Rd"]},
                          geometry=[LineString([(80.2, 13.0), (80.201, 13.001)])], crs=common.GEO_CRS)
    fs.to_file(tmp_path / "fs.geojson", driver="GeoJSON")
    rec = pd.DataFrame({"row_id": [0, 1], "year": [2021, 2021], "ward": [5.0, 6.0], "location": ["anna road ", "Unknown Lane"], "depth_class_verified": ["low", None]})
    g = cdmp.locate_records(rec, tmp_path / "fs.geojson")
    assert list(g.placed) == [True, False]
    assert g.geometry.iloc[1] is None or g.geometry.iloc[1].is_empty
    assert g.position_uncertainty_m.iloc[0] == cdmp.PRECISION_RADIUS_M["street"] and np.isnan(g.position_uncertainty_m.iloc[1])
    assert (g.evidence_class == "E3").all()


def test_same_name_other_ward_is_not_matched(tmp_path):
    fs = gpd.GeoDataFrame({"name": ["Main Road"], "ward": [1.0], "years": [[2015]], "prec": ["street"], "src": ["x"], "match": ["x"]},
                          geometry=[Point(80.2, 13.0)], crs=common.GEO_CRS)
    fs.to_file(tmp_path / "fs.geojson", driver="GeoJSON")
    g = cdmp.locate_records(pd.DataFrame({"row_id": [0], "year": [2015], "ward": [2.0], "location": ["Main Road"]}), tmp_path / "fs.geojson")
    assert not g.placed.iloc[0]


@real
def test_real_pdf_restores_lost_high_column():
    h = pd.read_csv(RAW / "reclaimchennai/data/cdmp/2026/datasets/inundation_history.csv")
    v, rec = cdmp.verify_depth_classes(h[h.pdf_page.isin([63, 93])], RAW / "gcc_cdmp/cdmp_2026.pdf")
    k = v[(v.pdf_page == 63) & (v.location == "Kamaraj salai")].iloc[0]
    assert pd.isna(k.depth_class_extracted) and k.depth_class_verified == "high"           # 3-5 ft column restored
    assert (v[v.pdf_page == 93].depth_class_verified != "very_high").all()                # 2021 page has no >5 ft mark
    assert rec.row_level_verified.all()


# --------------------------------------------------------------------------- reference comparisons
def test_dist_to_set_exact():
    d = reference.dist_to_set(gpd.GeoSeries([Point(0, 0), Point(10, 0)]).values, np.array([LineString([(0, 5), (20, 5)])]))
    assert np.allclose(d, [5, 5])


def test_grid_origin_check_detects_shift():
    comps = pd.DataFrame({"cells": [1, 1], "bbox_rows": ["10-10", "0-0"], "bbox_cols": ["5-5", "0-0"],
                          "centroid_x": [reference.GRID_X0 + 5.5 * 30, reference.GRID_X0 + 15], "centroid_y": [reference.GRID_Y0 - 10.5 * 30, reference.GRID_Y0 - 15]})
    assert reference.verify_grid_origin(comps)["origin_reproduced_exactly"]
    comps.loc[0, "centroid_x"] += 7
    assert not reference.verify_grid_origin(comps)["origin_reproduced_exactly"]


def _roads():
    return gpd.GeoDataFrame(geometry=[box(x, 0, x + 10, 1000) for x in range(0, 1000, 50)], crs=CRS)


def test_null_model_shows_no_association_for_random_reports():
    rng = np.random.default_rng(1)
    region = box(0, 0, 1000, 1000)
    roads = _roads()
    reps = reference.null_points(roads, region, 60, rng).assign(position_uncertainty_m=0)
    comps = gpd.GeoDataFrame({"radius_m": [5.0] * 40}, geometry=[Point(x, y) for x, y in rng.uniform(0, 1000, (40, 2))], crs=CRS)
    t = reference.compare_reports_to_components(reps, {"x": comps}, roads, region, thresholds=(100,), n_null=50, seed=2)
    assert 0.6 < t.ratio_to_null.iloc[0] < 1.6          # reports drawn from the null itself: no association


def test_null_model_detects_real_association():
    region = box(0, 0, 1000, 1000)
    roads = _roads()
    comps = gpd.GeoDataFrame({"radius_m": [5.0] * 10}, geometry=[Point(5, y) for y in range(0, 1000, 100)], crs=CRS)
    reps = gpd.GeoDataFrame({"position_uncertainty_m": [0.0] * 10}, geometry=[Point(5, y + 3) for y in range(0, 1000, 100)], crs=CRS)
    t = reference.compare_reports_to_components(reps, {"x": comps}, roads, region, thresholds=(50,), n_null=50, seed=3)
    assert t.share_reports_within.iloc[0] == 1.0 and t.share_null_draws_ge_observed.iloc[0] == 0.0


def test_sidecar_never_defines_negatives():
    m = reference.checker_sidecar("R", "n", "p", "s", "2026-11-28", "l", False, "points", "2021-01-01", "2021-12-31", True, True, None,
                                  {"1": "listed", "0": "NOT DEFINED"}, "m")
    assert "NOT DEFINED" in m["class_meaning"]["0"] and m["positional_accuracy_m"] is None


# --------------------------------------------------------------------------- exposure
def test_worldpop_partial_coverage_is_not_totalled(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    a = np.full((10, 10), -9999.0, "float32")
    a[:, :6] = 10.0                                         # columns 0-5 have data
    p = tmp_path / "wp.tif"
    with rasterio.open(p, "w", driver="GTiff", width=10, height=10, count=1, dtype="float32", crs=CRS, transform=from_origin(0, 1000, 100, 100), nodata=-9999.0) as d:
        d.write(a, 1)
    wards = gpd.GeoDataFrame({"ward_no": [1, 2]}, geometry=[box(0, 0, 500, 1000), box(500, 0, 1000, 1000)], crs=CRS)
    src = type("S", (), {"worldpop": p})()
    z, _ = exposure.worldpop_zonal(src, wards)
    assert z.loc[0, "wp_coverage_flag"] == "COMPLETE" and z.loc[0, "wp_population_2020"] == 500.0
    assert z.loc[1, "wp_coverage_flag"] == "PARTIAL_NOT_TOTALLED" and np.isnan(z.loc[1, "wp_population_2020"])   # NaN, never 0


def test_near_reported_includes_position_uncertainty():
    rep = gpd.GeoDataFrame({"position_uncertainty_m": [750.0]}, geometry=[Point(0, 0)], crs=CRS)
    f = gpd.GeoDataFrame(geometry=[Point(900, 0), Point(1100, 0)], crs=CRS)
    assert list(exposure.near_reported(f, rep, 250)) == [True, False]


# --------------------------------------------------------------------------- vulnerability
def _vt(n=12, seed=0):
    r = np.random.default_rng(seed)
    return pd.DataFrame({"slum_area_share": r.uniform(0, .4, n), "dist_public_health_km": r.uniform(0, 4, n), "relief_capacity_per_1000": r.uniform(0, 20, n)})


def test_protective_indicator_is_inverted():
    t = pd.DataFrame({"relief_capacity_per_1000": [0.0, 10.0], "slum_area_share": [0.0, 0.1], "dist_public_health_km": [1.0, 2.0]})
    n = vulnerability.normalise(t, vulnerability.USED)
    assert n.relief_capacity_per_1000.tolist() == [1.0, 0.0] and n.slum_area_share.tolist() == [0.0, 1.0]


def test_population_density_is_not_a_vulnerability_indicator():
    assert not any("density" in k for k in vulnerability.USED)


def test_missing_indicator_gives_no_composite():
    t = _vt()
    t.loc[0, "slum_area_share"] = np.nan
    _, idx = vulnerability.components(vulnerability.normalise(t, vulnerability.USED))
    assert np.isnan(idx.iloc[0]) and idx.iloc[1:].notna().all()


def test_sensitivity_outputs_bounded():
    s, corr, _ = vulnerability.sensitivity(_vt(40), n_dirichlet=50)
    assert s.spearman_vs_baseline.between(-1, 1).all() and corr.shape == (3, 3)


# --------------------------------------------------------------------------- population table QA
def test_ward_population_rejects_unreconciled_zone(tmp_path):
    rows = [{"zone": "1", "pdf_page": "1", "table_id": "1", "kind": "population", "Sl.No.": str(i), "Ward. No/Name": f"{i} X",
             "Total House Holds": "100", "Total Population": "400"} for i in (1, 2)]
    rows.append({"zone": "1", "pdf_page": "1", "table_id": "1", "kind": "population", "Sl.No.": "", "Ward. No/Name": "Total", "Total House Holds": "200", "Total Population": "999"})
    pd.DataFrame(rows).to_csv(tmp_path / "p.csv", index=False)
    src = type("S", (), {"population_csv": tmp_path / "p.csv"})()
    wards = gpd.GeoDataFrame({"ward_no": [1, 2], "zone_no": [1, 1]}, geometry=[box(0, 0, 1, 1)] * 2, crs=CRS)
    out, chk = layers.ward_population(src, wards)
    assert not chk.accepted.iloc[0] and len(out) == 0


# --------------------------------------------------------------------------- ML contract
def test_ml_contract_unlabelled_rows_are_null_not_zero(tmp_path):
    class C:
        G = tmp_path / "G"
        D = tmp_path / "D"
    C.G.mkdir()
    C.D.mkdir()
    pd.DataFrame({"ward_no": [1, 2], "cdmp_records_2015": [0, 3], "cdmp_records_2021": [2, 0], "population_density_cdmp_per_km2": [1, 2],
                  "exposure_index_provisional": [.1, .2], "vulnerability_index_provisional": [.3, np.nan]}).to_csv(C.D / "integrated_ward_comparison.csv", index=False)
    mlcontract.write_all(C)
    t = pd.read_csv(C.G / "ml_ward_event_table_presence_only.csv")
    assert set(t.reference_observation.dropna()) == {1.0} and t.reference_observation.isna().sum() == 2
    assert json.loads((C.G / "ml_data_contract.json").read_text())["label_policy"].startswith("presence-only")


# --------------------------------------------------------------------------- real-data smoke tests on the produced package
@pytest.mark.skipif(not (OUT / "A_evidence_reference/cdmp_inundation_records_all_years.csv").is_file(), reason="run outputs not present")
def test_smoke_outputs_consistent():
    rec = pd.read_csv(OUT / "A_evidence_reference/cdmp_inundation_records_all_years.csv")
    assert len(rec) == 1401 and (rec.year == 2021).sum() == 561 and (rec.year == 2015).sum() == 306
    g21 = gpd.read_file(OUT / "A_evidence_reference/cdmp_inundation_locations_2021.gpkg")
    assert g21.crs.to_epsg() == 32644 and (g21.year == 2021).all() and g21.placed.all()
    e = pd.read_csv(OUT / "B_exposure/exposure_indicators_by_ward.csv")
    assert len(e) == 200 and e.ward_no.is_unique
    assert e.loc[e.wp_coverage_flag != "COMPLETE", "wp_population_2020"].isna().all()
    v = pd.read_csv(OUT / "C_vulnerability/vulnerability_indicators_components_by_ward.csv")
    assert v.loc[~v.data_complete, "vulnerability_index_provisional"].isna().all()
    assert v.vulnerability_index_provisional.dropna().between(0, 1).all()
    c21 = pd.read_csv(OUT / "A_evidence_reference/comparison_2021_cdmp_vs_s1_brightvv.csv")
    assert {"null_mean_share", "ratio_to_null"} <= set(c21.columns)
    assert not any(k in " ".join(c21.columns).lower() for k in ("precision", "recall", "accuracy", "f1", "iou"))
    reg = pd.read_csv(OUT / "A_evidence_reference/evidence_register.csv")
    assert reg.evidence_id.is_unique and "E1" not in set(reg.evidence_class)          # no item was upgraded to E1


# --------------------------------------------------------------------------- SUS-1 overlay (synthetic grid with the accepted geometry)
def test_sus1_overlay_not_assessed_is_never_low(tmp_path):
    from rasterio.transform import Affine
    from dep2 import sus1_overlay
    tr = Affine(*sus1_overlay.SUS1_GRID["transform"])
    h, w = sus1_overlay.SUS1_GRID["shape"]
    pct = np.full((h, w), np.nan)
    dom = np.full((h, w), 255, "uint8")
    pct[0:10, 0:10] = 95.0; dom[0:10, 0:10] = 1          # high
    pct[0:10, 10:20] = 50.0; dom[0:10, 10:20] = 1        # assessed, not high
    dom[0:10, 20:30] = 2                                  # water signature: NOT ASSESSED
    x0, y0 = tr.c, tr.f
    wards = gpd.GeoDataFrame({"ward_no": [1]}, geometry=[box(x0, y0 - 300, x0 + 900, y0)], crs=CRS)
    fac = gpd.GeoDataFrame({"facility_id": ["a", "b", "c"], "ward_no": [1, 1, 1]},
                           geometry=[Point(x0 + 15, y0 - 15), Point(x0 + 315, y0 - 15), Point(x0 + 615, y0 - 15)], crs=CRS)
    t, f = sus1_overlay.overlay(pct, dom, tr, wards, fac, None, 90.0)
    assert t.cells_assessed.iloc[0] == 200 and t.cells_not_assessed.iloc[0] == 100
    assert t.share_assessed_area_pct_ge_90.iloc[0] == 0.5
    assert list(f.sus1_cell_state) == ["high", "assessed_not_high", "not_assessed"]


def test_sus1_overlay_refuses_other_grid(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    from dep2 import sus1_overlay
    for n in ("p.tif", "d.tif"):
        with rasterio.open(tmp_path / n, "w", driver="GTiff", width=5, height=5, count=1, dtype="float32", crs=CRS, transform=from_origin(0, 0, 30, 30), nodata=-9999) as d:
            d.write(np.zeros((5, 5), "float32"), 1)
    with pytest.raises(SystemExit, match="master grid"):
        sus1_overlay.read_sus1(tmp_path / "p.tif", tmp_path / "d.tif")
