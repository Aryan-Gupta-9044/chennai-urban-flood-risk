"""SAR change-detection flood mapping (local version; the same logic is mirrored in gee_sentinel1.py).
Inputs are backscatter in dB (VV). This is a PROXY flood label, not ground truth."""
import numpy as np


def detect_flood_change(pre_db, post_db, diff_threshold_db=-3.0, post_max_db=-15.0,
                        slope_deg=None, max_slope_deg=5.0, permanent_water=None):
    """Return uint8 array: 1 flood, 0 not flood, 255 nodata."""
    pre = np.asarray(pre_db, dtype="float64")
    post = np.asarray(post_db, dtype="float64")
    valid = np.isfinite(pre) & np.isfinite(post)
    flood = (post - pre < diff_threshold_db) & (post < post_max_db)
    if slope_deg is not None:
        flood &= np.asarray(slope_deg) <= max_slope_deg
    if permanent_water is not None:
        flood &= ~np.asarray(permanent_water, dtype=bool)
    out = np.where(flood & valid, 1, 0).astype("uint8")
    out[~valid] = 255
    return out
