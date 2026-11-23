"""Sentinel-1 flood extent via Google Earth Engine (needs one-time authentication).
NOTE: written to the public GEE API but NOT executed during packaging (no GEE access there)."""
import io
import zipfile
import requests


def init_ee(project=None):
    import ee
    try:
        ee.Initialize(project=project or None)
    except Exception:
        # Newer/older API variants: try without project
        ee.Initialize()
    return ee


def count_images(ee, geom, start, end):
    col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(geom).filterDate(start, end)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")))
    out = {}
    for p in ("ASCENDING", "DESCENDING"):
        out[p] = int(col.filter(ee.Filter.eq("orbitProperties_pass", p)).size().getInfo())
    return out


def flood_image(ee, geom, pre, post, orbit_pass, p):
    def col(win):
        return (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(geom).filterDate(win[0], win[1])
                .filter(ee.Filter.eq("instrumentMode", "IW"))
                .filter(ee.Filter.eq("orbitProperties_pass", orbit_pass))
                .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
                .select("VV"))
    pre_img = col(pre).median().focal_median(50, "circle", "meters")
    post_img = col(post).median().focal_median(50, "circle", "meters")
    diff = post_img.subtract(pre_img)
    flood = diff.lt(p["diff_threshold_db"]).And(post_img.lt(p["post_max_db"]))
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
    flood = flood.And(slope.lte(p["max_slope_deg"]))
    water = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0)
    flood = flood.And(water.lt(p["min_water_occurrence_pct"]))
    return flood.rename("flood").toByte().clip(geom)


def download_geotiff(ee, image, geom, out_path, epsg, scale):
    url = image.getDownloadURL({"region": geom, "scale": scale, "crs": f"EPSG:{epsg}", "format": "GEO_TIFF"})
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    data = r.content
    if data[:2] == b"PK":  # zipped
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = [n for n in z.namelist() if n.lower().endswith(".tif")][0]
            data = z.read(name)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path
