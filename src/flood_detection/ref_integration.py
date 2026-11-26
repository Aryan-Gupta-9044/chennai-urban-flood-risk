"""Flood-reference integration, stages R0-R2 (V2.3): intake validation, alignment report, readiness checklist.

READ-ONLY on every reference file (SHA-256 before/after). No reprojection or resampling of reference DATA is ever performed; geometry footprints are transformed only to MEASURE overlap.
Passing these checks means a file is technically parseable, georeferenced and documented. It does NOT make it an authoritative flood reference, and software validation is NOT flood-map
accuracy validation: no flood label is made, no agreement/accuracy metric is computed here (R3-R5 are not started). Day thresholds are analyst conventions, not validated limits."""
import hashlib
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

PASS, WARN, FAIL = "PASS", "WARNING", "FAIL"
KINDS = ("extent_raster", "extent_polygons", "points", "depth_points")
EXT = {".tif": "raster", ".tiff": "raster", ".geojson": "vector", ".json": "vector", ".gpkg": "vector", ".shp": "vector", ".csv": "table"}
REQUIRED_META = ("reference_id", "name", "producer", "source", "obtained_on", "licence", "kind", "obs_date")
DEFAULTS = {"close_days": 3, "max_days": 6, "min_coverage_candidate": 0.95, "full_coverage": 0.999, "max_obs_range_days": 14}
STATEMENT = ("Software validation is NOT flood-map accuracy validation. A PASS here means the file is parseable, georeferenced and documented; it does not make it an authoritative flood "
             "reference. No flood label, agreement or accuracy metric is produced at this stage.")
UNK = "UNCONFIRMED"


def F(code, level, message, **evidence): return {"code": code, "level": level, "message": message, "evidence": evidence}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def worst(findings): return FAIL if any(f["level"] == FAIL for f in findings) else WARN if any(f["level"] == WARN for f in findings) else PASS


def valid_mask(a):
    """ONE finite-data rule for every raster check (R0 and R1): a cell is valid only if it is not masked as NoData AND is finite (NaN, +inf, -inf are never valid, with or without a NoData value)."""
    return ~np.ma.getmaskarray(a) & np.isfinite(np.ma.getdata(a))


SHP_COMPANIONS = (".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix", ".atx", ".ixs", ".mxs", ".qpj")


def dataset_files(path):
    """Every file that belongs to the reference dataset: the file itself plus, for a Shapefile, its companions (.shx .dbf .prj .cpg .sbn .sbx .qix .fix .atx .ixs .mxs .qpj .shp.xml) and, for a GeoTIFF, its
    auxiliary files (.aux.xml, .ovr, .msk, .tfw, .wld) when present. All of them are hashed before and after intake."""
    path = Path(path); suf = path.suffix.lower(); st = path.stem.lower(); nm = path.name.lower(); out = [path]
    if not path.parent.is_dir(): return out
    for c in sorted(path.parent.iterdir()):
        if not c.is_file() or c == path: continue
        n = c.name.lower()
        if suf == ".shp" and ((n.startswith(st + ".") and c.suffix.lower() in SHP_COMPANIONS) or n == st + ".shp.xml"): out.append(c)
        elif suf in (".tif", ".tiff") and (n in (nm + ".aux.xml", nm + ".ovr", nm + ".msk", st + ".tfw", st + ".wld", st + ".aux.xml")): out.append(c)
    return out


def dataset_hashes(path): return {c.name: sha256_file(c) for c in dataset_files(path)}


def _known(v): return v not in (None, "", UNK) and UNK not in str(v)


_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_iso_date(v):
    """STRICT: the only accepted form is the ISO calendar date YYYY-MM-DD (ASCII digits, zero-padded, nothing before or after, a real calendar day). Time of day belongs in obs_time_of_day.
    Rejected, e.g.: '2021-11-05garbage', '2021-11-05T06:00:00Z', ' 2021-11-05', '20211105', '2021-1-5', '2021-02-30', numbers, None. A datetime.date object is accepted; a datetime is not."""
    if isinstance(v, datetime): return None
    if isinstance(v, date): return v
    if not isinstance(v, str) or _ISO_DATE.fullmatch(v) is None: return None
    try: return date.fromisoformat(v)
    except ValueError: return None


_parse_date = parse_iso_date


# ----------------------------------------------------------------------------------------------------------------------------------------------- R0
def meta_findings(meta, today):
    f = []
    if not isinstance(meta, dict): return [F("META_TYPE", FAIL, "metadata sidecar is not a JSON object")], None
    miss = [k for k in REQUIRED_META if k not in meta and not (k == "obs_date" and "obs_date_start" in meta)]
    unk = [k for k in REQUIRED_META if k in meta and not _known(meta[k])]
    if miss or unk: f.append(F("META_FIELDS", FAIL, "required provenance/metadata fields missing or UNCONFIRMED", missing=miss, unconfirmed=unk))
    else: f.append(F("META_FIELDS", PASS, "all required metadata fields are present (their truth is not verified by software)"))
    if meta.get("kind") not in KINDS: f.append(F("META_KIND", FAIL, f"kind must be one of {KINDS}", found=meta.get("kind")))
    lic_ok = meta.get("licence_permits_derived_stats")
    f.append(F("LICENCE", PASS if lic_ok is True else WARN, "licence permits derived statistics (as stated in the sidecar; not verified)" if lic_ok is True else "licence permission for derived statistics is not confirmed True", stated=meta.get("licence")))
    ind = meta.get("independent_of_s1")
    f.append(F("INDEPENDENCE", PASS if ind is True else FAIL if ind is None else WARN, {True: "declared independent of Sentinel-1 (stated, not verified)", False: "declared Sentinel-1-derived: consistency comparison only, not independent"}.get(ind, "independence from Sentinel-1 not stated")))
    f.append(F("METHOD_DOC", PASS if meta.get("production_method_documented") is True else WARN, "production method documented (as stated)" if meta.get("production_method_documented") is True else "production method not documented: independence cannot be judged"))
    pa = meta.get("positional_accuracy_m")
    f.append(F("POSITIONAL_ACCURACY", PASS if isinstance(pa, (int, float)) and pa >= 0 else WARN, f"positional accuracy stated: {pa} m" if isinstance(pa, (int, float)) and pa >= 0 else "positional accuracy unknown"))
    f.append(F("CLASS_MEANING", PASS if meta.get("class_meaning") else WARN, "class meaning documented" if meta.get("class_meaning") else "class meaning not documented"))
    # dates
    d0 = _parse_date(meta.get("obs_date_start", meta.get("obs_date"))); d1 = _parse_date(meta.get("obs_date_end", meta.get("obs_date_start", meta.get("obs_date")))); rng = None
    if d0 is None or d1 is None: f.append(F("DATE", FAIL, "observation date missing or not ISO YYYY-MM-DD", found=[meta.get("obs_date"), meta.get("obs_date_start"), meta.get("obs_date_end")]))
    elif d1 < d0: f.append(F("DATE", FAIL, "observation end date precedes start date", start=str(d0), end=str(d1)))
    elif d1 > today: f.append(F("DATE", FAIL, "observation date is in the future", end=str(d1), today=str(today)))
    else:
        rng = (d0, d1); f.append(F("DATE", WARN if (d1 - d0).days > DEFAULTS["max_obs_range_days"] else PASS, f"observation {d0}..{d1} ({(d1 - d0).days + 1} day(s))" + (" - range wider than the Sentinel-1 revisit" if (d1 - d0).days > DEFAULTS["max_obs_range_days"] else "")))
        if not meta.get("obs_time_of_day"): f.append(F("DATE_TIME", WARN, "time of day not stated; sub-daily offset to the Sentinel-1 overpass cannot be assessed"))
    return f, rng


def _crs(obj):
    from pyproj import CRS
    try: return CRS.from_user_input(obj)
    except Exception: return None


def _footprint_cov(bounds, crs, aoi_wgs):
    import geopandas as gpd
    from shapely.geometry import box
    fp = gpd.GeoSeries([box(*bounds)], crs=crs).to_crs(32644); a = gpd.GeoSeries([aoi_wgs], crs=4326).to_crs(32644)
    return float(a.intersection(fp.iloc[0]).area.iloc[0] / a.area.iloc[0]), [float(x) for x in gpd.GeoSeries([box(*bounds)], crs=crs).to_crs(4326).total_bounds]


def intake(path, meta, aoi_wgs, today=None):
    """R0. Returns a report dict; never raises on a bad file (the failure is the finding). The file is only ever opened for reading."""
    today = today or date.today(); path = Path(path); rep = {"file": str(path), "stage": "R0 intake", "statement": STATEMENT}
    findings, rng = meta_findings(meta, today); meta = meta if isinstance(meta, dict) else {}
    rep["obs_range"] = None if rng is None else [str(rng[0]), str(rng[1])]
    if not path.is_file(): findings.append(F("FILE", FAIL, "reference file not found", path=str(path))); rep.update(findings=findings, status=FAIL, info=None); return rep
    size = path.stat().st_size; rep["size_bytes"] = size; files = dataset_files(path); h0 = {c.name: sha256_file(c) for c in files}; rep["sha256_before"] = h0[path.name]; rep["dataset_files"] = sorted(h0); rep["dataset_sha256_before"] = h0
    if size == 0: findings.append(F("FILE", FAIL, "file is empty"))
    else:
        findings.append(F("FILE", PASS, f"file present, {size} bytes"))
        fmt = EXT.get(path.suffix.lower()); rep["format"] = fmt
        if path.suffix.lower() == ".shp":
            have = {c.suffix.lower() for c in files}; miss = [x for x in (".shx", ".dbf") if x not in have]
            findings.append(F("SHAPEFILE_PARTS", FAIL if miss else PASS, f"Shapefile is incomplete: missing {miss}" if miss else f"Shapefile dataset files hashed: {sorted(h0)}", files=sorted(h0), missing=miss))
        if fmt is None: findings.append(F("FORMAT", FAIL, f"unsupported format {path.suffix!r} (supported: {sorted(EXT)}); PDF/JPEG maps are qualitative only until georeferenced"))
        else:
            try: info = {"raster": _read_raster, "vector": _read_vector, "table": _read_table}[fmt](path, meta, findings, aoi_wgs)
            except Exception as e: info = None; findings.append(F("READ", FAIL, "file is unreadable or malformed", error=f"{type(e).__name__}: {str(e)[:200]}"))
            rep["info"] = info
    rep.setdefault("info", None); h1 = {c.name: sha256_file(c) for c in dataset_files(path) if c.exists()}; rep["sha256_after"] = h1.get(path.name); rep["dataset_sha256_after"] = h1; rep["unchanged"] = h0 == h1
    if h0 != h1: findings.append(F("INTEGRITY", FAIL, "reference dataset changed during intake", changed=sorted(k for k in set(h0) | set(h1) if h0.get(k) != h1.get(k))))
    rep["findings"] = findings; rep["status"] = worst(findings); return rep


def _crs_findings(file_crs, meta, findings):
    declared = meta.get("declared_crs"); fc = _crs(file_crs) if file_crs else None; dc = _crs(declared) if declared else None
    if declared and dc is None: findings.append(F("CRS", FAIL, "declared CRS is invalid", declared=str(declared))); return None
    if file_crs and fc is None: findings.append(F("CRS", FAIL, "embedded CRS cannot be interpreted", embedded=str(file_crs))); return None
    if fc is None and dc is None: findings.append(F("CRS", FAIL, "no CRS in the file and none declared: not georeferenced")); return None
    if fc is not None and dc is not None and not fc.equals(dc): findings.append(F("CRS", FAIL, "embedded CRS disagrees with the declared CRS", embedded=fc.to_string(), declared=dc.to_string())); return None
    crs = fc or dc; findings.append(F("CRS", PASS if fc is not None else WARN, f"CRS {crs.to_string()} ({'embedded' if fc is not None else 'DECLARED ONLY, not embedded in the file'}; {'geographic' if crs.is_geographic else 'projected'})")); return crs


def _kind_check(actual, meta, findings):
    k = meta.get("kind"); ok = {"raster": ("extent_raster",), "polygons": ("extent_polygons",), "points": ("points", "depth_points")}[actual]
    if k in KINDS and k not in ok: findings.append(F("KIND_MATCH", FAIL, f"declared kind {k!r} does not match the file content ({actual})"))
    elif k in KINDS: findings.append(F("KIND_MATCH", PASS, f"declared kind {k!r} matches the file content"))


def _read_raster(path, meta, findings, aoi_wgs):
    import rasterio
    with rasterio.open(path) as ds:
        crs = _crs_findings(ds.crs.to_wkt() if ds.crs else None, meta, findings); t = ds.transform; a = ds.read(1, masked=True); nd = ds.nodata
        info = {"kind": "raster", "crs": None if crs is None else crs.to_string(), "res": (abs(t.a), abs(t.e)), "shape": (ds.height, ds.width), "bounds": tuple(ds.bounds), "count": ds.count, "dtype": ds.dtypes[0], "nodata": nd, "transform": tuple(t)[:6]}
    _kind_check("raster", meta, findings)
    if t.b != 0 or t.d != 0: findings.append(F("RASTER_ROTATED", WARN, "raster transform is rotated/sheared; cell-wise comparison would need resampling"))
    if nd is None: findings.append(F("RASTER_NODATA", WARN, "no NoData value defined; invalid cells cannot be told from zeros"))
    vm = valid_mask(a); n_valid = int(vm.sum()); nonfin = int((~np.ma.getmaskarray(a) & ~np.isfinite(np.ma.getdata(a))).sum()); info["valid_cells"] = n_valid; info["nonfinite_cells"] = nonfin
    if nonfin: findings.append(F("RASTER_NONFINITE", WARN, f"{nonfin} NaN/+inf/-inf cell(s) are excluded from the valid data (never treated as zero, flooded or valid)", nonfinite_cells=nonfin))
    if n_valid == 0: findings.append(F("RASTER_DATA", FAIL, "raster has no valid (finite, non-NoData) cells"))
    else:
        vals = np.unique(np.ma.getdata(a)[vm]); info["values"] = [float(v) for v in vals[:25]]; cm = meta.get("class_meaning") or {}
        findings.append(F("RASTER_DATA", PASS, f"{n_valid} valid (finite, non-NoData) cells, {len(vals)} distinct value(s)"))
        if cm:
            unk = [float(v) for v in vals if str(int(v)) not in cm and str(v) not in cm] if len(vals) <= 25 else None
            findings.append(F("CLASS_VALUES", WARN if unk else PASS, "raster values not described by class_meaning" if unk else "all observed values are described by class_meaning", undocumented=unk))
    if crs is not None:
        cov, wgs = _footprint_cov(info["bounds"], crs, aoi_wgs); info["footprint_wgs84"] = wgs; info["aoi_footprint_coverage"] = cov; _cov_finding(cov, findings, "raster extent")
    return info


def _cov_finding(cov, findings, what, n_hit=None):
    zero = FAIL if (n_hit is None or n_hit == 0) else WARN                       # a point set has a near-zero bounding box by nature: FAIL only when no feature touches the AOI
    findings.append(F("SPATIAL_COVERAGE", zero if cov <= 0 else WARN if cov < DEFAULTS["full_coverage"] else PASS, f"{what} covers {100 * cov:.1f}% of the AOI (bounding-box footprint; a bounding box is not the mapped area)", coverage=round(cov, 4)))


def _geom_checks(gdf, findings, crs):
    n = len(gdf); g = gdf.geometry; empty = int((g.isna() | g.is_empty).sum()); gg = g[~(g.isna() | g.is_empty)]
    if n == 0: findings.append(F("GEOMETRY", FAIL, "no features")); return None
    bad = int((~gg.is_valid).sum()); types = sorted(set(gg.geom_type)); nonfinite = int((~np.isfinite(gg.total_bounds)).any()) if len(gg) else 0
    lvl = FAIL if (empty or bad or nonfinite or len(gg) == 0) else PASS
    findings.append(F("GEOMETRY", lvl, f"{n} features; {empty} null/empty; {bad} invalid; geometry types {types}", features=n, empty=empty, invalid=bad))
    if len(gg) == 0: return None
    kinds = {"Polygon": "polygons", "MultiPolygon": "polygons", "Point": "points", "MultiPoint": "points"}; ks = {kinds.get(t, "other") for t in types}
    if len(ks) != 1 or "other" in ks: findings.append(F("GEOMETRY_TYPE", FAIL, f"mixed or unsupported geometry types {types}")); return None
    kind = ks.pop()
    if kind == "polygons":
        z = int((gg.area == 0).sum()); findings.append(F("POLYGON_AREA", WARN if z else PASS, f"{z} zero-area polygon(s)" if z else "no zero-area polygons"))
    elif kind == "points":
        dup = int(gg.apply(lambda p: p.wkt).duplicated().sum()); findings.append(F("DUPLICATE_POINTS", WARN if dup else PASS, f"{dup} duplicate point location(s)" if dup else "no duplicate point locations"))
    if crs is not None and crs.is_geographic:
        b = gg.total_bounds
        if b[0] < -180 or b[2] > 180 or b[1] < -90 or b[3] > 90: findings.append(F("COORD_RANGE", FAIL, "coordinates outside valid longitude/latitude range (axis order or CRS wrong?)", bounds=[float(x) for x in b]))
        else: findings.append(F("COORD_RANGE", PASS, "coordinates within valid longitude/latitude range"))
    return kind


def _vector_info(gdf, kind, crs, findings, meta, aoi_wgs):
    _kind_check(kind, meta, findings); info = {"kind": kind, "crs": crs.to_string(), "n_features": len(gdf), "bounds": tuple(float(x) for x in gdf.geometry.total_bounds)}
    import geopandas as gpd
    cov, wgs = _footprint_cov(info["bounds"], crs, aoi_wgs); info["footprint_wgs84"] = wgs; info["aoi_footprint_coverage"] = cov
    a = gpd.GeoSeries([aoi_wgs], crs=4326).to_crs(crs).iloc[0]; info["n_features_in_aoi"] = int(gdf.geometry.intersects(a).sum()); _cov_finding(cov, findings, "feature extent", info["n_features_in_aoi"]); return info


def _read_vector(path, meta, findings, aoi_wgs):
    import geopandas as gpd
    gdf = gpd.read_file(path); crs = _crs_findings(gdf.crs.to_wkt() if gdf.crs else None, meta, findings)
    kind = _geom_checks(gdf, findings, crs)
    if crs is None or kind is None: return {"kind": kind, "crs": None if crs is None else crs.to_string(), "n_features": len(gdf)}
    if gdf.crs is None: gdf = gdf.set_crs(crs)
    return _vector_info(gdf, kind, crs, findings, meta, aoi_wgs)


def _read_table(path, meta, findings, aoi_wgs):
    import geopandas as gpd
    df = pd.read_csv(path); xc = meta.get("x_column") or next((c for c in df.columns if c.lower() in ("lon", "longitude", "x")), None); yc = meta.get("y_column") or next((c for c in df.columns if c.lower() in ("lat", "latitude", "y")), None)
    if xc not in df.columns or yc not in df.columns: findings.append(F("COORD_COLUMNS", FAIL, "no coordinate columns found (set x_column / y_column in the sidecar)", columns=list(df.columns))); return None
    crs = _crs_findings(None, meta, findings); x, y = pd.to_numeric(df[xc], errors="coerce"), pd.to_numeric(df[yc], errors="coerce"); badn = int((x.isna() | y.isna() | ~np.isfinite(x) | ~np.isfinite(y)).sum())
    if badn: findings.append(F("COORD_VALUES", FAIL, f"{badn} row(s) with missing/non-numeric/non-finite coordinates", rows=badn))
    ok = ~(x.isna() | y.isna()) & np.isfinite(x) & np.isfinite(y)
    if crs is None or not ok.any(): return None
    gdf = gpd.GeoDataFrame(df[ok].copy(), geometry=gpd.points_from_xy(x[ok], y[ok]), crs=crs); kind = _geom_checks(gdf, findings, crs)
    if kind != "points": return None
    return _vector_info(gdf, "points", crs, findings, meta, aoi_wgs)


# ----------------------------------------------------------------------------------------------------------------------------------------------- R1
def _need_date(v):
    d = parse_iso_date(v)
    if d is None: raise ValueError(f"not a strict ISO date YYYY-MM-DD: {v!r}")
    return d


def temporal(obs_range, scene_dates, windows=(), close=None, mx=None):
    close = DEFAULTS["close_days"] if close is None else close; mx = DEFAULTS["max_days"] if mx is None else mx; rows = []
    d0, d1 = (_need_date(obs_range[0]), _need_date(obs_range[1])) if obs_range else (None, None)
    for s in scene_dates:
        sd = _need_date(s)
        if d0 is None: rows.append({"s1_date": str(s), "offset_days": None, "abs_offset_days": None, "category": "NOT ASSESSED (no valid reference date)"}); continue
        off = 0 if d0 <= sd <= d1 else (sd - d1).days if sd > d1 else (sd - d0).days     # signed: + = Sentinel-1 AFTER the reference observation
        a = abs(off); cat = "within the reference observation range" if a == 0 else "close (<= %d d)" % close if a <= close else "within half a revisit (<= %d d)" % mx if a <= mx else "NOT temporally comparable (> %d d)" % mx
        rows.append({"s1_date": str(s), "offset_days": off, "abs_offset_days": a, "category": cat})
    wrows = []
    for nm, a_, b_ in windows:
        a_, b_ = _need_date(a_), _need_date(b_)
        wrows.append({"window": nm, "start": str(a_), "end": str(b_), "overlaps_reference_dates": None if d0 is None else (d0 <= b_ and d1 >= a_), "gap_days": None if d0 is None else max(0, (d0 - b_).days, (a_ - d1).days)})
    return pd.DataFrame(rows), pd.DataFrame(wrows)


def alignment(path, intake_rep, aoi_wgs, grid, scene_dates, windows=()):
    """R1. Measures mismatches only. Raster DATA is never reprojected or resampled; the AOI geometry is transformed to the raster's own CRS to count its own cells."""
    f = []; info = intake_rep.get("info") or {}; out = {"stage": "R1 alignment", "statement": STATEMENT, "grid": {"crs": str(grid.crs), "res_m": grid.res}}
    if not info.get("crs"): f.append(F("ALIGN_SPATIAL", FAIL, "no usable georeferenced content: spatial alignment cannot be assessed"))
    else:
        gc, rc = _crs(grid.crs), _crs(info["crs"]); same = bool(gc and rc and gc.equals(rc)); cov = info.get("aoi_footprint_coverage"); out["crs_same_as_grid"] = same; out["aoi_footprint_coverage"] = cov
        f.append(F("GRID_CRS", PASS if same else WARN, "reference CRS equals the Sentinel-1 analysis CRS" if same else f"reference CRS {info['crs']} differs from the analysis CRS {grid.crs}; no reprojection was performed"))
        if info["kind"] == "raster":
            rx, ry = info["res"]; ratio = rx / grid.res; out["resolution_ratio_to_grid"] = ratio
            rel = "equal" if math.isclose(rx, grid.res, rel_tol=1e-6) and math.isclose(ry, grid.res, rel_tol=1e-6) else "non-square" if not math.isclose(rx, ry, rel_tol=1e-6) else ("coarser" if ratio > 1 else "finer") + (" (integer multiple)" if min(ratio, 1 / ratio) == 1 / max(ratio, 1 / ratio) and math.isclose(max(ratio, 1 / ratio), round(max(ratio, 1 / ratio)), rel_tol=1e-6) else " (non-integer ratio)")
            f.append(F("GRID_RES", PASS if rel == "equal" else WARN, f"reference resolution {rx:g} x {ry:g} vs grid {grid.res:g} m: {rel}; cell-wise comparison would need resampling (not done)" if rel != "equal" else f"reference resolution equals the grid ({grid.res:g} m)"))
            if same:
                from affine import Affine
                t = Affine(*info["transform"]); off = (((t.c - grid.transform.c) / grid.res + 1e-9) % 1, ((grid.transform.f - t.f) / grid.res + 1e-9) % 1); out["origin_offset_cells"] = [float(off[0]), float(off[1])]
                aligned = all(o < 1e-6 or o > 1 - 1e-6 for o in off)
                f.append(F("GRID_ORIGIN", PASS if aligned else WARN, "reference cell origin is aligned with the grid" if aligned else f"reference cells are offset from the grid by {off[0]:.3f}/{off[1]:.3f} of a cell; resampling would be needed"))
            spat = _raster_valid(path, info, aoi_wgs); out["raster_aoi"] = spat
            if spat: f.append(F("AOI_VALID_COVERAGE", FAIL if spat["valid_share_of_aoi_cells"] == 0 else WARN if spat["valid_share_of_aoi_cells"] < DEFAULTS["full_coverage"] else PASS, f"{100 * spat['valid_share_of_aoi_cells']:.1f}% of the reference's own cells inside the AOI hold valid data (finite, non-NoData cells; AOI cells counted on the reference's own grid, no resampling)", **spat))
        else:
            out["n_features_in_aoi"] = info.get("n_features_in_aoi"); f.append(F("FEATURES_IN_AOI", FAIL if not info.get("n_features_in_aoi") else PASS, f"{info.get('n_features_in_aoi')} of {info.get('n_features')} feature(s) intersect the AOI"))
        f.append(F("ALIGN_SPATIAL", FAIL if not cov else WARN if cov < DEFAULTS["full_coverage"] else PASS, f"AOI footprint coverage {0 if cov is None else 100 * cov:.1f}%"))
    tdf, wdf = temporal(intake_rep.get("obs_range"), scene_dates, windows); out["temporal"] = tdf.to_dict("records"); out["windows"] = wdf.to_dict("records")
    if tdf["abs_offset_days"].notna().any():
        m = int(tdf["abs_offset_days"].min()); out["min_abs_offset_days"] = m; best = tdf.loc[tdf["abs_offset_days"].idxmin(), "s1_date"]
        f.append(F("ALIGN_TEMPORAL", PASS if m <= DEFAULTS["close_days"] else WARN if m <= DEFAULTS["max_days"] else FAIL, f"closest Sentinel-1 date {best} is {m} day(s) from the reference observation (conventions: <= {DEFAULTS['close_days']} d close, <= {DEFAULTS['max_days']} d half-revisit)", closest=best, min_abs_offset_days=m))
        n_cmp = int((tdf["abs_offset_days"] <= DEFAULTS["max_days"]).sum()); out["n_dates_within_max"] = n_cmp
    else: f.append(F("ALIGN_TEMPORAL", FAIL, "temporal alignment cannot be assessed (no valid reference date)"))
    if len(wdf) and wdf["overlaps_reference_dates"].notna().any():
        for _, w in wdf.iterrows(): f.append(F("EVENT_WINDOW", PASS if w["overlaps_reference_dates"] else WARN, f"window {w['window']} {w['start']}..{w['end']}: " + ("overlaps the reference dates" if w["overlaps_reference_dates"] else f"does NOT overlap the reference dates (gap {w['gap_days']} d)")))
    out["findings"] = f; out["status"] = worst(f); out["temporal_df"], out["windows_df"] = tdf, wdf; return out


def _raster_valid(path, info, aoi_wgs):
    import geopandas as gpd
    import rasterio
    from rasterio import features
    with rasterio.open(path) as ds:
        a = ds.read(1, masked=True); aoi = gpd.GeoSeries([aoi_wgs], crs=4326).to_crs(ds.crs).iloc[0]
        inside = features.geometry_mask([aoi], out_shape=a.shape, transform=ds.transform, invert=True, all_touched=False)
    n_in = int(inside.sum())
    if n_in == 0: return {"aoi_cells_in_reference": 0, "valid_share_of_aoi_cells": 0.0}
    v = int((inside & valid_mask(a)).sum()); return {"aoi_cells_in_reference": n_in, "valid_cells_in_aoi": v, "valid_share_of_aoi_cells": v / n_in}


# ----------------------------------------------------------------------------------------------------------------------------------------------- R2
ALIGNMENT_POLICY = (
    "R2 ALIGNMENT POLICY (documented choice). For a RASTER reference, a CRS, resolution or cell-origin mismatch with the Sentinel-1 analysis grid, or a rotated transform, means any cell-wise comparison "
    "would first need resampling/reprojection of the reference data - a methodological choice (method, aggregation, class handling) that can change results. Such mismatches therefore do NOT silently "
    "pass: they are listed as ALIGNMENT CONDITIONS and the candidate-label verdict states that an explicit team decision on alignment is required. By default they do not change the existing eligibility "
    "thresholds (coverage, temporal, independence, ...); with strict_alignment=True (CLI --strict-alignment) each condition becomes a BLOCKER. For vector/point references a CRS difference is routine "
    "geometry reprojection (no data resampling) and is only recorded as evidence, not as a condition. Nothing here performs any resampling or reprojection.")


def alignment_conditions(intake_rep, align_rep):
    """Raster-only mismatches that would require resampling/reprojection of the reference before a cell-wise comparison (see ALIGNMENT_POLICY)."""
    if (intake_rep.get("info") or {}).get("kind") != "raster": return []
    return [f"{x['code']}: {x['message']}" for x in intake_rep["findings"] + align_rep["findings"] if x["level"] == WARN and x["code"] in ("GRID_CRS", "GRID_RES", "GRID_ORIGIN", "RASTER_ROTATED")]


def readiness(meta, intake_rep, align_rep, strict_alignment=False):
    """R2. Four independent verdicts, each with blockers (reasons) and evidence. Never READY/VALIDATED: the strongest outcome is ELIGIBLE FOR TEAM REVIEW."""
    meta = meta if isinstance(meta, dict) else {}; lv = {x["code"]: x for x in intake_rep["findings"] + align_rep["findings"]}; ev = lambda *c: {k: lv[k]["message"] for k in c if k in lv}      # noqa: E731
    fail_codes = [x["code"] for x in intake_rep["findings"] if x["level"] == FAIL]; kind = meta.get("kind"); info = intake_rep.get("info") or {}
    m = align_rep.get("min_abs_offset_days"); cov = info.get("aoi_footprint_coverage"); prov = [k for k in ("producer", "source", "obtained_on") if not _known(meta.get(k))]
    def verdict(blockers, ok_label, no_label, evid): return {"verdict": ok_label if not blockers else no_label, "blockers": blockers, "evidence": evid}
    b = []
    if fail_codes: b.append(f"intake has FAIL finding(s): {sorted(set(fail_codes))}")
    if kind not in ("extent_raster", "extent_polygons"): b.append(f"kind {kind!r} is not a mapped flood extent (raster/polygons)")
    if meta.get("independent_of_s1") is not True: b.append("independence from Sentinel-1 is not established as True (Sentinel-1-derived or unknown): consistency comparison only")
    if meta.get("production_method_documented") is not True: b.append("production method not documented")
    if meta.get("licence_permits_derived_stats") is not True: b.append("licence permission for derived statistics not confirmed")
    if not meta.get("class_meaning"): b.append("class meaning not documented")
    if not isinstance(meta.get("positional_accuracy_m"), (int, float)): b.append("positional accuracy unknown")
    if m is None or m > DEFAULTS["close_days"]: b.append(f"no Sentinel-1 date within {DEFAULTS['close_days']} days of the reference observation (closest: {m})")
    if cov is None or cov < DEFAULTS["min_coverage_candidate"]: b.append(f"AOI coverage {None if cov is None else round(cov, 3)} < {DEFAULTS['min_coverage_candidate']} (partial coverage: sub-area use would need a team decision)")
    rs = (align_rep.get("raster_aoi") or {}).get("valid_share_of_aoi_cells")
    if rs is not None and rs < DEFAULTS["min_coverage_candidate"]: b.append(f"only {100 * rs:.1f}% of the AOI has valid reference data")
    conds = alignment_conditions(intake_rep, align_rep)
    if strict_alignment: b += [f"alignment mismatch (strict policy): {c}" for c in conds]
    ok_label = "ELIGIBLE FOR TEAM REVIEW as a reference for a later candidate-label comparison (authoritativeness and evaluation design NOT decided; R3 not started)"
    if conds and not strict_alignment: ok_label += " - ONLY WITH AN EXPLICIT TEAM DECISION ON ALIGNMENT (resampling/reprojection of the reference would be required; see alignment_conditions)"
    cand = verdict(b, ok_label, "NOT READY for candidate-label comparison", ev("INDEPENDENCE", "METHOD_DOC", "LICENCE", "POSITIONAL_ACCURACY", "SPATIAL_COVERAGE", "ALIGN_TEMPORAL"))
    cand["alignment_conditions"] = conds; cand["team_decision_required"] = ["alignment"] if (conds and not b) else []
    p = [x for x in ([f"intake has FAIL finding(s): {sorted(set(fail_codes))}"] if fail_codes else [])]
    if kind not in ("points", "depth_points"): p.append(f"kind {kind!r} is not a set of reported locations")
    if not info.get("n_features_in_aoi"): p.append("no reported location falls inside the AOI")
    if m is None or m > DEFAULTS["max_days"]: p.append(f"reported dates are more than {DEFAULTS['max_days']} days from every Sentinel-1 date (closest: {m})")
    pres = verdict(p, "ELIGIBLE FOR TEAM REVIEW for a presence-only comparison (a report is a presence; absence of a report is NOT absence of flooding; no recall/accuracy/false-positive claim)", "NOT READY for presence-only comparison", ev("FEATURES_IN_AOI", "ALIGN_TEMPORAL", "SPATIAL_COVERAGE"))
    q = ([f"provenance fields missing or UNCONFIRMED: {prov}"] if prov else []) + ([] if intake_rep.get("obs_range") else ["observation date unknown"]) + (["file unreadable/not found"] if any(c in fail_codes for c in ("FILE", "READ", "FORMAT")) else [])
    qual = verdict(q, "ELIGIBLE FOR TEAM REVIEW for qualitative historical comparison only (narrative/visual; no metric)", "NOT USABLE even qualitatively until provenance and date are known", ev("META_FIELDS", "DATE"))
    ok = [("CANDIDATE_LABEL_COMPARISON", cand), ("PRESENCE_ONLY", pres), ("QUALITATIVE_ONLY", qual)]; primary = next((n for n, v in ok if not v["blockers"]), "UNUSABLE")
    return {"stage": "R2 readiness", "statement": STATEMENT, "reference_id": meta.get("reference_id"), "primary_class": primary, "candidate_label_comparison": cand, "presence_only_comparison": pres, "qualitative_comparison": qual,
            "authoritative_reference": "NOT ASSESSED BY SOFTWARE - requires the team gate decision", "alignment_policy": ALIGNMENT_POLICY, "strict_alignment": strict_alignment, "intake_status": intake_rep["status"], "alignment_status": align_rep["status"],
            "note": "Verdicts are independent and conservative; the highest eligible class is reported as primary. None of them is accuracy validation."}
