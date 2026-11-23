"""S1B Earth Engine layer graph + tiled GeoTIFF download (SAR flood PROXY, unvalidated).

STATUS: the pure-Python helpers (tile_plan, tile_geometry) are unit-tested. The Earth Engine graph (`build_layers`),
`verify_live` and `download_tile` need a live Earth Engine session and are NOT tested until run on the user's machine.

Design: every layer is computed in Earth Engine on a 10 m grid whose origin is the 30 m master-grid origin (so every
3x3 block of 10 m pixels is exactly one master-grid cell). Local code then aggregates 10 m -> 30 m (s1_report.block_mean)."""
import io
import time
import zipfile
import requests
from .s1_params import NODATA

# Layer order == band order in every downloaded tile.
LAYERS = [
    "pre_median_db", "pre_std_db", "pre_count", "post_db", "diff_db",
    "candidate", "mask_prev_dark", "mask_perm_water", "mask_steep", "mask_hand",
    "flood_proxy", "valid", "slope_deg", "hand_m", "water_occurrence_pct",
]


def tile_plan(grid, tile_px=512, res=10.0):
    """Tiles covering the master grid at `res` metres. Returns list of dicts (x0, ytop, w, h, row, col) in grid CRS.
    Origin = master-grid top-left, so 10 m pixels nest exactly inside 30 m cells."""
    f = int(round(grid.res / res))
    if abs(f * res - grid.res) > 1e-9:
        raise ValueError("master resolution must be an integer multiple of the processing resolution")
    W, H = grid.width * f, grid.height * f
    x_left, y_top = grid.transform.c, grid.transform.f
    tiles = []
    for ri, r0 in enumerate(range(0, H, tile_px)):
        for ci, c0 in enumerate(range(0, W, tile_px)):
            w, h = min(tile_px, W - c0), min(tile_px, H - r0)
            tiles.append({"row": ri, "col": ci, "r0": r0, "c0": c0, "w": w, "h": h,
                          "x0": x_left + c0 * res, "ytop": y_top - r0 * res, "res": res})
    return tiles


def tile_geometry(t):
    """(x0, y_bottom, x1, y_top, crs_transform) for an Earth Engine download of tile t."""
    x1 = t["x0"] + t["w"] * t["res"]
    yb = t["ytop"] - t["h"] * t["res"]
    return t["x0"], yb, x1, t["ytop"], [t["res"], 0, t["x0"], 0, -t["res"], t["ytop"]]


def verify_live(ee, event_cfg):
    """Re-read the pinned scenes' properties directly from Earth Engine NOW; return list of problems (empty = OK)."""
    ids = event_cfg["scene_ids"]["pre"] + event_cfg["scene_ids"]["post"]
    want = event_cfg["orbit"]
    problems = []
    for sid in ids:
        try:
            p = ee.Image(f"COPERNICUS/S1_GRD/{sid}").toDictionary().getInfo()
        except Exception as e:  # noqa
            problems.append(f"{sid}: cannot be read from Earth Engine ({str(e)[:120]})")
            continue
        if str(p.get("orbitProperties_pass")).upper() != want["direction"].upper():
            problems.append(f"{sid}: pass {p.get('orbitProperties_pass')} != {want['direction']}")
        if int(p.get("relativeOrbitNumber_start", -1)) != int(want["rel_orbit"]):
            problems.append(f"{sid}: relative orbit {p.get('relativeOrbitNumber_start')} != {want['rel_orbit']}")
        if "VV" not in list(p.get("transmitterReceiverPolarisation", [])):
            problems.append(f"{sid}: no VV polarisation")
        if p.get("instrumentMode") != "IW":
            problems.append(f"{sid}: instrument mode {p.get('instrumentMode')} != IW")
    return problems


def build_layers(ee, event_cfg, p):
    """Return one ee.Image with the bands in LAYERS (float32, masked pixels -> NODATA when exported with unmask)."""
    ids = event_cfg["scene_ids"]

    def prep(sid):
        im = ee.Image(f"COPERNICUS/S1_GRD/{sid}").select("VV")     # already dB, GRD-border-noise/thermal-noise removed, calibrated, orthorectified
        if p["speckle_filter"] == "focal_median":
            im = im.focalMedian(p["speckle_radius_m"], "circle", "meters")
        return im

    pre = ee.ImageCollection([prep(s) for s in ids["pre"]])
    pre_med = pre.median().rename("pre_median_db")
    pre_std = pre.reduce(ee.Reducer.stdDev()).rename("pre_std_db")
    pre_cnt = pre.reduce(ee.Reducer.count()).rename("pre_count")
    post = prep(ids["post"][0]).rename("post_db")
    diff = post.subtract(pre_med).rename("diff_db")
    valid = pre_cnt.gte(p["min_pre_obs"]).And(post.mask()).And(pre_med.mask()).rename("valid")

    cand = diff.lt(p["diff_threshold_db"]).And(post.lt(p["post_max_db"]))
    if p.get("use_std_test"):
        cand = cand.And(diff.lt(pre_std.multiply(-p["std_k"])))
    cand = cand.rename("candidate")

    prev_dark = pre_med.lt(p["pre_water_db"]).rename("mask_prev_dark")
    occ = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0).rename("water_occurrence_pct")
    perm = occ.gte(p["min_water_occurrence_pct"]).rename("mask_perm_water")
    slope = ee.Terrain.slope(ee.Image("NASA/NASADEM_HGT/001").select("elevation")).rename("slope_deg")
    steep = slope.gt(p["max_slope_deg"]).rename("mask_steep")
    hand = ee.Image("MERIT/Hydro/v1_0_1").select("hnd").rename("hand_m")
    if p.get("max_hand_m") is None:
        hand_mask = ee.Image(0).rename("mask_hand")          # not applied; HAND kept as diagnostic only
    else:
        hand_mask = hand.gt(p["max_hand_m"]).unmask(0).rename("mask_hand")

    keep = prev_dark.Not().And(perm.Not()).And(steep.Not()).And(hand_mask.Not())
    flood = cand.And(keep).selfMask()
    flood = flood.updateMask(flood.connectedPixelCount(100, True).gte(p["min_cluster_pixels_10m"]))
    flood = flood.unmask(0).rename("flood_proxy")

    bands = [pre_med, pre_std, pre_cnt, post, diff, cand, prev_dark, perm, steep, hand_mask, flood, valid, slope, hand, occ]
    img = ee.Image.cat([b.unmask(NODATA).toFloat() for b in bands])
    # slope/HAND/water: product masks are still reported where SAR is invalid; `valid` band is authoritative.
    return img.select(LAYERS)


def _extract_tif(data):
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = [n for n in z.namelist() if n.lower().endswith(".tif")][0]
            return z.read(name)
    return data


def download_tile(ee, image, t, epsg, out_path, retries=3):
    """Download one tile as multi-band GeoTIFF (skips if it exists). Raises after `retries` failed attempts."""
    from pathlib import Path
    out = Path(out_path)
    if out.exists() and out.stat().st_size > 0:
        return out, "cached"
    x0, yb, x1, yt, tr = tile_geometry(t)
    region = ee.Geometry.Rectangle([x0, yb, x1, yt], proj=f"EPSG:{epsg}", geodesic=False)
    last = None
    for k in range(retries):
        try:
            url = image.getDownloadURL({"region": region, "crs": f"EPSG:{epsg}", "crs_transform": tr, "format": "GEO_TIFF"})
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            out.write_bytes(_extract_tif(r.content))
            return out, "downloaded"
        except Exception as e:  # noqa
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"tile r{t['row']}c{t['col']} failed after {retries} attempts: {str(last)[:300]}")


def start_drive_export(ee, image, grid, epsg, name, folder="chennai_flood_s1b"):
    """Alternative: one Export.image.toDrive task for the whole master-grid extent at 10 m (monitor in the Tasks tab)."""
    l, b, r, t = grid.bounds
    region = ee.Geometry.Rectangle([l, b, r, t], proj=f"EPSG:{epsg}", geodesic=False)
    f = int(round(grid.res / 10.0))
    task = ee.batch.Export.image.toDrive(image=image, description=name, folder=folder, fileNamePrefix=name,
                                         region=region, crs=f"EPSG:{epsg}",
                                         crsTransform=[10, 0, l, 0, -10, t], maxPixels=1e10, fileFormat="GeoTIFF")
    task.start()
    return task
