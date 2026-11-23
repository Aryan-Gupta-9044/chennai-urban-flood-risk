"""Windowed raster reads (local file or remote COG via GDAL /vsicurl)."""
import math
import rasterio
from rasterio.windows import Window, from_bounds


def read_bounds(path_or_url, bounds_wgs84, band=1):
    """Read the part of a (geographic CRS) raster covering bounds_wgs84.
    Returns (array, transform, crs, nodata) or None if there is no overlap."""
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
               GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2", GDAL_HTTP_TIMEOUT="60")
    with rasterio.Env(**env):
        with rasterio.open(path_or_url) as ds:
            l, b, r, t = bounds_wgs84
            if ds.crs is not None and not ds.crs.is_geographic:
                # V2 fix: projected rasters (e.g. a UTM DEM supplied by the user) need bounds in their own CRS
                from rasterio.warp import transform_bounds
                l, b, r, t = transform_bounds("EPSG:4326", ds.crs, l, b, r, t, densify_pts=21)
            dl, db, dr, dt = ds.bounds
            il, ib, ir, it = max(l, dl), max(b, db), min(r, dr), min(t, dt)
            if il >= ir or ib >= it:
                return None
            w = from_bounds(il, ib, ir, it, ds.transform)
            ro = max(int(math.floor(w.row_off)), 0)
            co = max(int(math.floor(w.col_off)), 0)
            h = min(int(math.ceil(w.row_off + w.height)) - ro, ds.height - ro)
            wd = min(int(math.ceil(w.col_off + w.width)) - co, ds.width - co)
            win = Window(co, ro, wd, h)
            arr = ds.read(band, window=win)
            return arr, ds.window_transform(win), ds.crs, ds.nodata
