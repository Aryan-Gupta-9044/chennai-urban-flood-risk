"""ML-EXP-1 tests: evidence rules (no negatives, no leakage), spatial folds, null-calibrated association, guards."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import geopandas as gpd  # noqa: E402
from shapely.geometry import box  # noqa: E402

from analytics import explore, presence_only, ward_features  # noqa: E402

CRS = "EPSG:32644"


def _grid_wards(nx=12, ny=10, size=1000.0, zones_x=4):
    rows = []
    for i in range(nx):
        for j in range(ny):
            rows.append({"ward_no": i * ny + j + 1, "zone_no": i // (nx // zones_x) + 1, "area_km2": 1.0, "geometry": box(i * size, j * size, (i + 1) * size, (j + 1) * size)})
    return gpd.GeoDataFrame(rows, crs=CRS)


def test_feature_spec_has_no_label_derived_model_features():
    used = [n for n, _, u, _ in ward_features.FEATURE_SPEC if u]
    assert not any(k in n for n in used for k in ("reported", "cdmp_records", "near_reported", "osmin"))
    assert "area_km2" not in used                      # area is a CONTROL, not a predictor of flooding
    assert "chirps_2021_event_mm_coarse" not in used    # coarse context only
    assert "wp_pop_density_2020" not in used            # partial coverage: separate source, not in models


def test_feature_sets_exclude_label_derived_columns():
    for name, feats in presence_only.FEATURE_SETS.items():
        assert not any(("reported" in f) or ("records" in f) for f in feats), name


def test_buffered_zone_folds_never_leak():
    w = _grid_wards()
    t = w.drop(columns="geometry")
    for z, tr, te, nb in presence_only.buffered_zone_folds(t, w, buffer_m=500):
        assert set(tr).isdisjoint(te)
        test_zone = w.iloc[te].union_all().buffer(500)
        assert not w.iloc[tr].intersects(test_zone).any()
        assert nb > 0                                   # neighbouring wards were removed


def test_pb_analysis_detects_real_signal_and_rejects_noise():
    w = _grid_wards()
    rng = np.random.default_rng(0)
    t = w.drop(columns="geometry").copy()
    for f in set().union(*presence_only.FEATURE_SETS.values()):
        t[f] = rng.normal(size=len(t)) if f != "area_km2" else 1.0 + rng.uniform(size=len(t))
    t["sus_a_mean_pct"] = rng.uniform(0, 100, len(t))
    signal = (t.sus_a_mean_pct + rng.normal(0, 10, len(t))) > 50
    t["reported_2015"] = np.where(signal, 1.0, np.nan)
    t["reported_2021"] = np.where(rng.uniform(size=len(t)) > 0.5, 1.0, np.nan)    # pure noise
    import analytics.presence_only as po
    keep = po.FEATURE_SETS
    po.FEATURE_SETS = {"F1": ["sus_a_mean_pct"]}
    try:
        res, *_ = po.evaluate(t, w, kinds=("logistic_l2",), n_perm={"logistic_l2": 30}, buffer_m=10)
    finally:
        po.FEATURE_SETS = keep
    r15 = res[res.event == 2015].iloc[0]
    r21 = res[res.event == 2021].iloc[0]
    assert r15.pb_auc_oof > 0.8 and r15.p_perm_one_sided < 0.05
    assert r21.p_perm_one_sided > 0.05


def test_unreported_is_unlabelled_not_negative_in_feature_table():
    # reported_* columns are 1 or NaN only (never 0)
    p = ROOT / "outputs/ml_exploratory_v1/tables/ward_feature_matrix.csv"
    if not p.is_file():
        pytest.skip("ML-EXP-1 outputs not built")
    t = pd.read_csv(p)
    for yr in (2015, 2021):
        assert set(t[f"reported_{yr}"].dropna().unique()) == {1.0}
        assert ((t[f"cdmp_records_{yr}"] == 0) == t[f"reported_{yr}"].isna()).all()


def test_morans_i_sign():
    w = _grid_wards(6, 6, zones_x=3)
    W = explore.contiguity(w)
    ids = w.ward_no.values
    xy = np.array([[g.centroid.x, g.centroid.y] for g in w.geometry])
    clustered = pd.Series(xy[:, 0], index=ids)
    checker = pd.Series(((xy[:, 0] // 1000 + xy[:, 1] // 1000) % 2).astype(float), index=ids)
    assert explore.morans_i(clustered, W, n_perm=99)["morans_i"] > 0.5
    # queen contiguity on a checkerboard mixes rook (opposite) and diagonal (same) neighbours -> clearly below the clustered case
    assert explore.morans_i(checker, W, n_perm=99)["morans_i"] < 0.1


def test_prepare_drops_incomplete_wards_and_reports_them():
    t = pd.DataFrame({"ward_no": [1, 2, 3], **{f: [1.0, 2.0, 3.0] for f in explore.model_features()}})
    t.loc[1, "slum_area_share"] = np.nan
    ids, Z, dropped = explore.prepare(t)
    assert dropped == [2] and list(ids) == [1, 3]


def test_grid_check_refuses_other_grid(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    p = tmp_path / "x.tif"
    with rasterio.open(p, "w", driver="GTiff", width=3, height=3, count=1, dtype="float32", crs=CRS, transform=from_origin(0, 0, 30, 30)) as d:
        d.write(np.zeros((3, 3), "float32"), 1)
    with pytest.raises(SystemExit, match="master grid"):
        ward_features.check_grid(p)


def test_output_guard_refuses_protected_paths():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_ward_analytics as b
    for p in ("outputs/susceptibility_v1", "outputs/dep2_local_run_01/X", "data/processed"):
        with pytest.raises(SystemExit):
            b.guard(ROOT / p)
    b.guard(ROOT / "outputs/ml_exploratory_v1_test")


def test_pipeline_runner_skips_legacy_rf_by_default(monkeypatch):
    src = (ROOT / "scripts/run_pipeline.py").read_text(encoding="utf-8")
    assert 'CHENNAI_ALLOW_LEGACY_RF' in src and 'steps = [s for s in steps if s[0] != "G"]' in src
    assert (ROOT / "scripts/train_random_forest.py").is_file()          # preserved for traceability
    assert (ROOT / "scripts/_legacy/run_pipeline_v0_before_rf_gate.py").is_file()
