"""S1B local processing: tile assembly, 10 m -> 30 m aggregation, descriptive statistics, processing report.
All functions are pure NumPy/rasterio and are unit-tested on SYNTHETIC arrays (logic tests only, not data)."""
import html
import numpy as np
import rasterio
from .s1_params import NODATA
from .s1_proxy import LAYERS

CONTINUOUS = ["pre_median_db", "pre_std_db", "pre_count", "post_db", "diff_db", "slope_deg", "hand_m", "water_occurrence_pct"]
FLAGS = ["candidate", "mask_prev_dark", "mask_perm_water", "mask_steep", "mask_hand", "flood_proxy", "valid"]


def block_view(a, f):
    h, w = a.shape[-2:]
    if h % f or w % f:
        raise ValueError(f"array {a.shape} not divisible by block {f}")
    return a.reshape(a.shape[:-2] + (h // f, f, w // f, f))


def block_mean(a, f=3, nodata=NODATA, min_valid_frac=0.5):
    """Mean of non-nodata pixels in each f x f block; NODATA where fewer than min_valid_frac of the pixels are valid."""
    v = block_view(np.asarray(a, dtype="float64"), f)
    ok = (v != nodata) & np.isfinite(v)
    n = ok.sum(axis=(-3, -1))
    s = np.where(ok, v, 0.0).sum(axis=(-3, -1))
    out = np.full(n.shape, nodata, dtype="float32")
    good = n >= max(1, int(np.ceil(min_valid_frac * f * f)))
    out[good] = (s[good] / n[good]).astype("float32")
    return out


def assemble(tile_files, tiles, grid, f=3, n_bands=len(LAYERS)):
    """Place downloaded tiles into one (bands, H10, W10) array; verifies CRS, pixel size, origin and band count of each tile."""
    H, W = grid.height * f, grid.width * f
    full = np.full((n_bands, H, W), NODATA, dtype="float32")
    for t, p in zip(tiles, tile_files):
        with rasterio.open(p) as ds:
            if ds.count != n_bands:
                raise ValueError(f"{p}: {ds.count} bands, expected {n_bands}")
            if str(ds.crs.to_epsg()) != str(grid.crs).split(":")[-1]:
                raise ValueError(f"{p}: CRS {ds.crs} != {grid.crs}")
            tr = ds.transform
            if abs(tr.a - t["res"]) > 1e-6 or abs(-tr.e - t["res"]) > 1e-6 or abs(tr.c - t["x0"]) > 1e-3 or abs(tr.f - t["ytop"]) > 1e-3:
                raise ValueError(f"{p}: grid misaligned (origin {tr.c},{tr.f} res {tr.a}) vs expected ({t['x0']},{t['ytop']}) res {t['res']}")
            if (ds.width, ds.height) != (t["w"], t["h"]):
                raise ValueError(f"{p}: size {ds.width}x{ds.height} != {t['w']}x{t['h']}")
            full[:, t["r0"]:t["r0"] + t["h"], t["c0"]:t["c0"] + t["w"]] = ds.read().astype("float32")
    return full


def aggregate(stack10, f=3, flood_fraction_threshold=0.5, min_valid_frac=0.5):
    """10 m stack -> 30 m products. Flags become fractions of valid 10 m pixels; flood_proxy_30m = fraction >= threshold."""
    idx = {n: i for i, n in enumerate(LAYERS)}
    valid10 = (stack10[idx["valid"]] == 1)
    out = {}
    nvalid = block_view(valid10.astype("float64"), f).sum(axis=(-3, -1))
    ok = nvalid >= max(1, int(np.ceil(min_valid_frac * f * f)))
    out["valid_30m"] = ok.astype("uint8")
    SAR = ("pre_median_db", "pre_std_db", "pre_count", "post_db", "diff_db")
    for n in CONTINUOUS:
        a = stack10[idx[n]].copy()
        if n in SAR:
            a[~valid10] = NODATA
        out[n] = block_mean(a, f, min_valid_frac=min_valid_frac)
        if n in SAR:
            out[n][~ok] = NODATA
    for n in FLAGS:
        if n == "valid":
            continue
        v = np.where(valid10, stack10[idx[n]], 0.0)
        frac = block_view(v, f).sum(axis=(-3, -1)) / np.maximum(nvalid, 1)
        out[n + "_frac"] = np.where(ok, frac, NODATA).astype("float32")
    fr = out["flood_proxy_frac"]
    out["flood_proxy_30m"] = np.where(ok, (fr >= flood_fraction_threshold).astype("uint8"), 255).astype("uint8")   # 255 = no valid SAR data
    return out


def compute_stats(stack10, prod30, inside30, grid, f=3):
    """Descriptive statistics only. NOT accuracy. All areas in km2 restricted to the study-area boundary."""
    idx = {n: i for i, n in enumerate(LAYERS)}
    inside10 = np.kron(inside30.astype("uint8"), np.ones((f, f), dtype="uint8")).astype(bool)
    valid = (stack10[idx["valid"]] == 1) & inside10
    px10, px30 = (grid.res / f) ** 2 / 1e6, grid.res ** 2 / 1e6
    g = lambda n: stack10[idx[n]] == 1
    cand, flood = g("candidate") & valid, g("flood_proxy") & valid
    pd_, pw, st, hd = g("mask_prev_dark"), g("mask_perm_water"), g("mask_steep"), g("mask_hand")
    s = {
        "study_area_cells_30m": int(inside30.sum()),
        "study_area_km2": round(float(inside30.sum() * px30), 3),
        "valid_sar_cells_10m": int(valid.sum()),
        "valid_sar_pct_of_study_area": round(100 * float(valid.sum()) / max(1, inside10.sum()), 2),
        "candidate_pixels_10m": int(cand.sum()), "candidate_km2": round(float(cand.sum() * px10), 3),
        "candidate_removed_by_prev_dark_10m": int((cand & pd_).sum()),
        "candidate_removed_by_permanent_water_10m": int((cand & pw).sum()),
        "candidate_removed_by_steep_slope_10m": int((cand & st).sum()),
        "candidate_removed_by_hand_10m": int((cand & hd).sum()),
        "candidate_removed_by_any_mask_10m": int((cand & (pd_ | pw | st | hd)).sum()),
        "flood_proxy_pixels_10m": int(flood.sum()), "flood_proxy_km2_10m": round(float(flood.sum() * px10), 3),
    }
    f30 = (prod30["flood_proxy_30m"] == 1) & inside30
    s["flood_proxy_cells_30m"] = int(f30.sum())
    s["flood_proxy_km2_30m"] = round(float(f30.sum() * px30), 3)
    s["flood_proxy_pct_of_study_area_30m"] = round(100 * s["flood_proxy_km2_30m"] / s["study_area_km2"], 2) if s["study_area_km2"] else None
    s["no_valid_sar_cells_30m"] = int(((prod30["flood_proxy_30m"] == 255) & inside30).sum())
    # Diagnostics: where is the remaining proxy? (terrain false-positive investigation)
    slope, hand = stack10[idx["slope_deg"]], stack10[idx["hand_m"]]
    fl_s = slope[flood]
    fl_s = fl_s[fl_s != NODATA]
    s["flood_proxy_slope_deg"] = ({"mean": round(float(fl_s.mean()), 2), "p95": round(float(np.percentile(fl_s, 95)), 2),
                                   "share_gt_2deg_pct": round(float(100 * (fl_s > 2).mean()), 1)} if fl_s.size else None)
    fl_h = hand[flood]
    fl_h = fl_h[fl_h != NODATA]
    bins = [(0, 2), (2, 5), (5, 10), (10, 15), (15, 1e9)]
    s["flood_proxy_by_hand_m"] = ({f"{lo}-{hi if hi < 1e8 else 'inf'}": int(((fl_h >= lo) & (fl_h < hi)).sum()) for lo, hi in bins}
                                  if fl_h.size else None)
    s["flood_proxy_hand_gt15m_pct"] = round(float(100 * (fl_h >= 15).mean()), 1) if fl_h.size else None
    d = stack10[idx["diff_db"]][flood]
    d = d[d != NODATA]
    s["flood_proxy_mean_diff_db"] = round(float(d.mean()), 2) if d.size else None
    return s


def limitations(p, event):
    return [
        "SAR-derived PROXY of inundation. It is NOT independently verified flood extent and no accuracy, precision, recall or validation is claimed.",
        "Single post-event acquisition (%s). Water may have receded or peaked at another time; the proxy is a snapshot at that overpass only." % event.get("post_date", "12 Nov 2015"),
        "Single polarisation (VV). Cross-pol (VH) was not used.",
        "Urban areas: double-bounce from buildings raises backscatter, so flooded streets between buildings are usually MISSED (expected omission); "
        "radar shadow/layover and smooth surfaces (tarmac, runways, wet sand) can produce false positives.",
        "Terrain: GRD in Earth Engine is orthorectified but NOT radiometrically terrain-flattened. Slope and HAND masks are crude screens; "
        "Chennai is very flat so terrain effects are small but not zero, and HAND (MERIT Hydro ~90 m) is coarse.",
        "Speckle: handled by a %s filter of radius %s m on each scene; this smooths small features and can erode thin flooded areas." % (p["speckle_filter"], p["speckle_radius_m"]),
        "Thresholds (%s dB change, %s dB post-event max) are STARTING values from the literature, NOT tuned on this event and NOT calibrated." % (p["diff_threshold_db"], p["post_max_db"]),
        "Permanent-water mask uses JRC Global Surface Water occurrence >= %s%%; seasonal tanks/lakes/Adyar-Cooum-Buckingham channels may be partly masked or partly flagged." % p["min_water_occurrence_pct"],
        "Vegetated/agricultural flooding and wind-roughened or flood-calm water can behave differently from the open-water assumption.",
        "Pre-event composite uses four earlier acquisitions of the same relative orbit (92, descending): Aug-Oct 2015, i.e. dry/monsoon-transition conditions rather than a long baseline.",
        "Independent references (ALOS-2, RISAT-1A, EOS-04, IITM logs) have NOT been compared in this step; use scripts/compare_reference.py only for AGREEMENT with a reference, which is not accuracy.",
    ]


def render_html(meta, stats, lims, images, scene_rows):
    e = html.escape
    rows = "".join(f"<tr><td>{e(s['role'])}</td><td>{e(s['scene'])}</td><td>{e(str(s.get('date','')))}</td><td>{e(str(s.get('abs_orbit','')))}</td>"
                   f"<td>{e(str(s.get('gee_rel_orbit','')))}</td><td>{e(str(s.get('gee_pass','')))}</td></tr>" for s in scene_rows)
    prm = "".join(f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>" for k, v in meta["params"].items())
    st = "".join(f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>" for k, v in stats.items())
    imgs = "".join(f"<h3>{e(t)}</h3><img src='{e(p)}' style='max-width:100%'>" for t, p in images)
    li = "".join(f"<li>{e(x)}</li>" for x in lims)
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>S1B processing report - {e(meta['event'])}</title>
<style>body{{font-family:Segoe UI,Arial;max-width:980px;margin:2em auto}}table{{border-collapse:collapse}}td,th{{border:1px solid #bbb;padding:3px 8px;font-size:13px}}
.warn{{background:#fff3cd;border:1px solid #e0c36a;padding:8px}}</style></head><body>
<h1>Sentinel-1 flood-extent PROXY - {e(meta['event'])}</h1>
<p class='warn'><b>SAR-derived proxy. Not independently verified. No accuracy or validation claimed.</b> Event role: exploratory.</p>
<h2>Run</h2><table><tr><td>run id</td><td>{e(meta['run_id'])}</td></tr><tr><td>generated</td><td>{e(meta['generated'])}</td></tr>
<tr><td>mode</td><td>{e(meta['mode'])}</td></tr><tr><td>CRS</td><td>{e(meta['crs'])}</td></tr>
<tr><td>processing resolution</td><td>{meta['processing_res_m']} m</td></tr><tr><td>output (master grid) resolution</td><td>{meta['output_res_m']} m</td></tr>
<tr><td>grid size (cells)</td><td>{e(str(meta['grid_shape']))}</td></tr><tr><td>EE project</td><td>{e(str(meta.get('ee_project')))}</td></tr></table>
<h2>Pinned scenes</h2><table><tr><th>role</th><th>scene id</th><th>date</th><th>abs orbit</th><th>EE rel orbit</th><th>pass</th></tr>{rows}</table>
<h2>Parameters</h2><table>{prm}</table><h2>Descriptive statistics (not accuracy)</h2><table>{st}</table>
<h2>Maps</h2>{imgs}<h2>Limitations</h2><ul>{li}</ul></body></html>"""
