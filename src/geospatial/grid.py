"""Master analysis grid: EPSG:32644, 30 m, snapped to the study-area bounding box."""
import math
from dataclasses import dataclass
import numpy as np
import rasterio
from rasterio import features
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling


@dataclass
class Grid:
    crs: str
    transform: object
    width: int
    height: int
    res: float

    @property
    def shape(self):
        return (self.height, self.width)

    @property
    def extent(self):  # left, right, bottom, top  (for matplotlib imshow)
        t = self.transform
        return (t.c, t.c + t.a * self.width, t.f + t.e * self.height, t.f)

    @property
    def bounds(self):
        l, r, b, t = self.extent
        return (l, b, r, t)


def make_master_grid(bounds_utm, res=30.0, epsg=32644, pad_cells=2):
    minx, miny, maxx, maxy = bounds_utm
    minx = math.floor(minx / res) * res - pad_cells * res
    miny = math.floor(miny / res) * res - pad_cells * res
    maxx = math.ceil(maxx / res) * res + pad_cells * res
    maxy = math.ceil(maxy / res) * res + pad_cells * res
    w = int(round((maxx - minx) / res))
    h = int(round((maxy - miny) / res))
    return Grid(f"EPSG:{epsg}", from_origin(minx, maxy, res, res), w, h, res)


def inside_mask(grid, geoms):
    """True where the pixel centre lies inside any geometry."""
    return features.geometry_mask(list(geoms), out_shape=grid.shape, transform=grid.transform,
                                  invert=True, all_touched=False)


def write_raster(path, arr, grid, nodata, description=None, dtype=None):
    arr = np.asarray(arr)
    dtype = dtype or str(arr.dtype)
    with rasterio.open(path, "w", driver="GTiff", height=grid.height, width=grid.width, count=1,
                       dtype=dtype, crs=grid.crs, transform=grid.transform, nodata=nodata,
                       compress="deflate", tiled=True) as dst:
        dst.write(arr.astype(dtype), 1)
        if description:
            dst.set_band_description(1, description)


def read_raster(path):
    with rasterio.open(path) as ds:
        return ds.read(1), ds.nodata, ds.transform, ds.crs


def to_grid(src_arr, src_transform, src_crs, grid, resampling=Resampling.bilinear,
            src_nodata=None, dst_nodata=-9999.0, dtype="float32"):
    dst = np.full(grid.shape, dst_nodata, dtype=dtype)
    reproject(source=src_arr, destination=dst, src_transform=src_transform, src_crs=src_crs,
              dst_transform=grid.transform, dst_crs=grid.crs, resampling=resampling,
              src_nodata=src_nodata, dst_nodata=dst_nodata)
    return dst
