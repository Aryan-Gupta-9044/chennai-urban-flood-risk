"""CHIRPS v3 DAILY_SAT helpers (pure NumPy/shapely/rasterio; unit-tested on SYNTHETIC arrays - Earth Engine calls live in the scripts).

Rules: native grid only (no reproject/resample); NoData is never 0 mm; coverage is measured against the ACTUAL study-area polygon
(exact polygon-cell intersection), never only its bounding box; thresholds are reported, never silently lowered."""
import numpy as np
from rasterio.transform import Affine
from shapely.geometry import box

DATASET_ID = "UCSB-CHC/CHIRPS/V3/DAILY_SAT"
BAND = "precipitation"
EXPORT_NODATA = -9999.0           # OUR export sentinel (applied with unmask in the probe); CHIRPS' own mask encoding is established by the probe, not assumed
UNITS_EXPECTED = "mm/d"
DAY_DEFINITION = ("PROVISIONAL / NOT VERIFIED: CHIRPS v3 daily values are pentad totals split into days using IMERG Late V07 (SAT). "
                  "Daily date labels are consistent labels from that disaggregation, NOT verified local (IST) observation-day windows.")
LICENCE_NOTE = ("DISCREPANCY: Earth Engine catalog says public domain (CC0-style waiver); CHC page says CC BY 4.0. "
                "Attribute under CC BY 4.0 (stricter). Citation: Climate Hazards Center Infrared Precipitation with Stations version 3, "
                "CHIRPS3 Data Repository, doi:10.15780/G2JQ0P (2025); Funk et al. (2026) Sci Data 13, 718, doi:10.1038/s41597-026-07096-4.")
REFERENCES = {"gee_catalog": "https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHC_CHIRPS_V3_DAILY_SAT",
              "chc_page": "https://chc.ucsb.edu/node/497", "chc_archive": "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/",
              "chc_daily_readme": "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/readme.txt"}
INDEPENDENCE_NOTE = "SAT is IMERG-split but CHIRPS itself blends station data, so it is not independent of gauge observations. Not validated."


def grid_from_ee_projection(proj):
    """ee Projection.getInfo() dict -> (crs_string, Affine). Requires a north-up affine transform; refuses anything else."""
    if not proj or "crs" not in proj or "transform" not in proj:
        raise ValueError(f"unexpected projection description: {proj!r}")
    a, b, c, d, e, f = [float(v) for v in proj["transform"]]
    if abs(b) > 0 or abs(d) > 0 or a <= 0 or e >= 0:
        raise ValueError(f"grid is not a north-up regular grid: {proj['transform']}")
    return proj["crs"], Affine(a, 0.0, c, 0.0, e, f)


def snap_window(transform, bounds, pad_cells=1):
    """Whole-cell window (col0, row0, ncols, nrows) covering `bounds` (minx,miny,maxx,maxy) plus pad cells, ON the native grid."""
    minx, miny, maxx, maxy = bounds
    c0 = int(np.floor((minx - transform.c) / transform.a)) - pad_cells
    c1 = int(np.ceil((maxx - transform.c) / transform.a)) + pad_cells
    r0 = int(np.floor((maxy - transform.f) / transform.e)) - pad_cells
    r1 = int(np.ceil((miny - transform.f) / transform.e)) + pad_cells
    return c0, r0, c1 - c0, r1 - r0


def window_transform(transform, win):
    c0, r0, _, _ = win
    return Affine(transform.a, 0.0, transform.c + c0 * transform.a, 0.0, transform.e, transform.f + r0 * transform.e)


def window_bounds(transform, win):
    c0, r0, nc, nr = win
    x0 = transform.c + c0 * transform.a; y0 = transform.f + r0 * transform.e
    return (x0, y0 + nr * transform.e, x0 + nc * transform.a, y0)


def aoi_cell_weights(wtransform, shape, aoi):
    """Exact share of the AOI POLYGON's area in each cell of the (window) grid (single shared implementation: rainfall.cell_weights, so the
    acquisition and the rainfall workflow use ONE cell convention, rainfall.CELL_CONVENTION). Returns (weights, touches) where touches =
    any positive-area overlap. Uses the polygon itself, not its bounding box."""
    from . import rainfall
    w = rainfall.cell_weights(wtransform, shape, aoi)
    return w, w > 0


def coverage(valid, weights):
    """valid: bool array (True = CHIRPS pixel has data). Returns AOI-area coverage (0..1) and cell counts over cells that touch the AOI."""
    touch = weights > 0
    n = int(touch.sum()); v = int((valid & touch).sum())
    return {"aoi_area_coverage": float(weights[valid & touch].sum() / weights[touch].sum()) if n else 0.0,
            "cells_touching_aoi": n, "cells_valid": v, "cells_missing": n - v,
            "aoi_inside_window": float(weights.sum())}


def check_export(precip, valid, nodata=EXPORT_NODATA):
    """Consistency of an exported [precipitation, valid-mask] pair. Returns a list of problems (empty = consistent)."""
    p = np.asarray(precip, dtype="float64"); v = np.asarray(valid)
    probs = []
    if p.shape != v.shape: return [f"shape mismatch {p.shape} vs {v.shape}"]
    if not np.isin(v, (0, 1)).all(): probs.append("valid band contains values other than 0/1")
    vb = v == 1
    nd = p == nodata
    if np.isnan(p).any(): probs.append(f"{int(np.isnan(p).sum())} NaN cells in precipitation band (expected the {nodata} sentinel)")
    if (nd & vb).any(): probs.append(f"{int((nd & vb).sum())} cells are valid per mask but hold the NoData sentinel")
    if (~nd & ~vb).any(): probs.append(f"{int((~nd & ~vb).sum())} masked cells hold a data value (masked cells should carry the sentinel, not 0 or a rainfall value)")
    if (p[vb] < 0).any(): probs.append(f"{int((p[vb] < 0).sum())} negative rainfall values in valid cells")
    return probs


def continuity(dates, expected):
    """dates: dates found in the collection. Returns missing / duplicated / unexpected dates relative to the expected list."""
    from collections import Counter
    cnt = Counter(dates); exp = set(expected)
    return {"missing": [d for d in expected if d not in cnt], "duplicated": sorted(d for d, n in cnt.items() if n > 1),
            "unexpected": sorted(d for d in cnt if d not in exp), "found": len(dates), "expected": len(expected)}


def temporal_completeness(per_date_cov, expected, min_coverage=0.95):
    """Share of the expected dates whose AOI-area coverage >= min_coverage. A date absent from per_date_cov counts as NOT meeting it."""
    ok = [d for d in expected if per_date_cov.get(d) is not None and per_date_cov[d] >= min_coverage]
    return {"dates_meeting": len(ok), "dates_expected": len(expected), "percent": 100.0 * len(ok) / len(expected) if expected else 0.0,
            "failing": [d for d in expected if d not in set(ok)]}


def verdict(min_coverage, test_cov, completeness, cont, export_problems, server_problems=()):
    """('STOP', reasons) or ('PROCEED-TO-REVIEW', []). Never lowers the threshold. Even PROCEED waits for the user's decision.
    A temporal-completeness figure only counts when the server-side calculation was verified: any export failure, missing validated test image or
    server_problems => STOP (the figure is then UNVERIFIED and must not be presented as a coverage result)."""
    why = []
    if cont["missing"] or cont["duplicated"] or cont["unexpected"]:
        why.append(f"date problem: missing={len(cont['missing'])} duplicated={len(cont['duplicated'])} unexpected={len(cont['unexpected'])}")
    if export_problems:
        why.append("exported test image failed validation: " + "; ".join(export_problems))
    if not test_cov:
        why.append("no exported test image passed validation, so no coverage figure (local or server-side) can be trusted")
    if server_problems:
        why.append("server-side coverage calculation NOT verified: " + "; ".join(server_problems))
    if completeness is None:
        why.append("temporal completeness was not computed")
    low = [d for d, c in test_cov.items() if c < min_coverage]
    if low:
        why.append(f"AOI-area coverage below {min_coverage:.0%} on test date(s): " + ", ".join(f"{d} ({test_cov[d]:.1%})" for d in low))
    if completeness is not None and completeness["dates_meeting"] < completeness["dates_expected"]:
        why.append(f"temporal completeness {completeness['percent']:.1f}% ({completeness['dates_meeting']}/{completeness['dates_expected']} dates meet {min_coverage:.0%})")
    return ("STOP" if why else "PROCEED-TO-REVIEW"), why


def download_params(crs, wtransform, shape):
    """getDownloadURL parameters requesting the EXACT native-grid window. Per the installed ee docs: `crs_transform` (snake_case) + `dimensions`
    [width, height] define an exact rectangle on that lattice; `region` and `scale` are ignored/not allowed alongside them, so neither is passed.
    wtransform = transform of the WINDOW's top-left cell (an integer number of native cells from the global origin); shape = (rows, cols).
    NOTE: Earth Engine implements this as a reproject onto the SAME lattice (identity re-gridding); that is verified, not assumed, by the probe's
    server-sample comparison against native cell-centre values."""
    H, W = shape
    return {"crs": crs, "crs_transform": [wtransform.a, 0.0, wtransform.c, 0.0, wtransform.e, wtransform.f], "dimensions": [int(W), int(H)], "format": "GEO_TIFF"}


def check_export_grid(ds_transform, ds_shape, ds_crs, exp_transform, exp_shape, native_transform, crs, tol=1e-9):
    """Problems (empty = ok) comparing a downloaded GeoTIFF's georeferencing with the requested native-grid window."""
    p = []
    if ds_crs is None or str(ds_crs).upper().replace("EPSG:", "") != str(crs).upper().replace("EPSG:", ""):
        p.append(f"CRS {ds_crs} != native {crs}")
    if abs(ds_transform.a - native_transform.a) > tol or abs(ds_transform.e - native_transform.e) > tol:
        p.append(f"pixel size [{ds_transform.a}, {-ds_transform.e}] != native [{native_transform.a}, {-native_transform.e}]")
    offc = (ds_transform.c - native_transform.c) / native_transform.a; offr = (ds_transform.f - native_transform.f) / native_transform.e
    if abs(offc - round(offc)) > 1e-6 or abs(offr - round(offr)) > 1e-6:
        p.append("export is not aligned to the native grid")
    if tuple(ds_shape) != tuple(exp_shape):
        p.append(f"shape {list(ds_shape)} != expected {list(exp_shape)}")
    if abs(ds_transform.c - exp_transform.c) > 1e-6 or abs(ds_transform.f - exp_transform.f) > 1e-6:
        p.append(f"origin ({ds_transform.c}, {ds_transform.f}) != requested window origin ({exp_transform.c}, {exp_transform.f})")
    return p


def server_row_problems(ncell, cells_seen, valid_cells, cov, weights_touching, tol=0.02):
    """Sanity of one server-side per-date row. cells_seen = native pixels selected by the cell-union geometry (must equal ncell, else the geometry/
    projection/transform is not selecting the intended cells); cov must lie between the sum of the `valid_cells` SMALLEST and LARGEST cell weights."""
    if cells_seen is None or cov is None or valid_cells is None:
        return ["server row has null values"]
    p = []
    if int(cells_seen) != int(ncell):
        p.append(f"server geometry selected {cells_seen} pixels, expected {ncell}")
    k = int(valid_cells)
    if not (0 <= k <= int(ncell)):
        return p + [f"valid_cells {valid_cells} outside 0..{ncell}"]
    w = sorted(float(x) for x in weights_touching)
    lo = sum(w[:k]); hi = sum(w[len(w) - k:]) if k else 0.0
    if not (lo - tol <= float(cov) <= hi + tol):
        p.append(f"coverage {cov:.4f} impossible for {k} valid cells (bounds {lo:.4f}..{hi:.4f})")
    return p


def compare_server_local(server_cov, server_valid, local_cov, local_valid, tol=0.02):
    p = []
    if server_cov is None or abs(float(server_cov) - float(local_cov)) > tol:
        p.append(f"server coverage {server_cov} vs exported-file coverage {local_cov:.4f} (tolerance {tol})")
    if server_valid is None or int(server_valid) != int(local_valid):
        p.append(f"server valid cells {server_valid} vs exported-file valid cells {local_valid}")
    return p


REQUEST_KEYS = ("crs", "crs_transform", "dimensions", "format")           # the ONLY request fields ever recorded (documented getDownloadURL keys we use)


def sanitize_request(req):
    """JSON-safe, whitelisted copy of a download request. Earth Engine's getDownloadURL MUTATES the dict it is given (it inserts `request['image'] = self`,
    an ee.Image), so the manifest must never serialise the dict that was passed to it: take this copy BEFORE the call, pass a different copy to ee."""
    out = {}
    for k in REQUEST_KEYS:
        if k not in req: continue
        v = req[k]
        if isinstance(v, tuple): v = list(v)
        if not (v is None or isinstance(v, (str, int, float, bool)) or (isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v))):
            raise TypeError(f"request field {k!r} holds a non-JSON value of type {type(v).__name__}")
        out[k] = v
    return out


def json_safe(obj, _path="$", dropped=None):
    """Convert to strictly JSON-safe data. Unknown objects (e.g. ee.Image, credentials) are DROPPED and replaced by a marker naming only their TYPE and
    location; the drops are listed in `dropped` so they stay visible. Strings that look like signed download URLs are cut at '?'."""
    import datetime as _dt
    import pathlib
    dropped = [] if dropped is None else dropped
    if obj is None or isinstance(obj, (bool, int)): return obj
    if isinstance(obj, float): return obj if np.isfinite(obj) else None
    if isinstance(obj, str): return obj.split("?")[0] if obj.startswith(("http://", "https://")) and "?" in obj else obj
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, np.ndarray): return [json_safe(x, f"{_path}[]", dropped) for x in obj.tolist()]
    if isinstance(obj, Affine): return [obj.a, obj.b, obj.c, obj.d, obj.e, obj.f]
    if isinstance(obj, (_dt.date, _dt.datetime)): return obj.isoformat()
    if isinstance(obj, pathlib.PurePath): return str(obj)
    if isinstance(obj, dict): return {str(k): json_safe(v, f"{_path}.{k}", dropped) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)): return [json_safe(v, f"{_path}[{i}]", dropped) for i, v in enumerate(obj)]
    dropped.append({"path": _path, "type": type(obj).__name__})
    return f"<DROPPED non-JSON object of type {type(obj).__name__}>"


def manifest_file_record(*, name, date_iso, sha256, nbytes, mtime_utc, provenance, request_sanitized, request_note, http_status, content_type, url_host, info, problems):
    """One manifest entry built from scalars only (never from the object passed to Earth Engine)."""
    return {"file": name, "date": date_iso, "sha256": sha256, "bytes": int(nbytes), "mtime_utc": mtime_utc, "provenance": provenance,
            "request_params": request_sanitized, "request_params_note": request_note, "http_status": http_status, "content_type": content_type,
            "request_url_host": url_host, "raster": info, "validation_problems": list(problems)}


# ---- Earth Engine geometry builders (take the `ee` module as an argument so the REAL installed API signatures can be exercised in tests).
# Signatures per ee 1.7.x: Point(coords, proj, *args, **kwargs) [NO geodesic]; Rectangle/Polygon/MultiPolygon(coords, proj, geodesic, ...);
# Geometry(geo_json, proj, geodesic, evenOdd). Everything is passed by keyword so a positional slip cannot shift an argument.
def ee_point(ee, x, y, crs):
    return ee.Geometry.Point(coords=[float(x), float(y)], proj=crs)


def ee_rectangle(ee, bounds, crs):
    return ee.Geometry.Rectangle(coords=[float(v) for v in bounds], proj=crs, geodesic=False)


def ee_multipolygon_from_rects(ee, rects, crs):
    """rects: iterable of (x0, y0, x1, y1) in `crs`."""
    return ee.Geometry.MultiPolygon(coords=[[[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]] for x0, y0, x1, y1 in rects], proj=crs, geodesic=False)


def ee_geometry_from_geojson(ee, geojson, crs):
    import json
    return ee.Geometry(geo_json=json.loads(json.dumps(geojson)), proj=crs, geodesic=False)      # json round-trip: tuples -> lists for the EE client
