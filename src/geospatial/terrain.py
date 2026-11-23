import numpy as np


def slope_degrees(dem, res, nodata=-9999.0):
    """Slope (degrees) by central differences. dem in metres, res = cell size in metres.
    Cells without a valid neighbour become nodata."""
    z = np.where(dem == nodata, np.nan, dem).astype("float64")
    gy, gx = np.gradient(z, res)
    s = np.degrees(np.arctan(np.hypot(gx, gy)))
    return np.where(np.isnan(s), nodata, s).astype("float32")
