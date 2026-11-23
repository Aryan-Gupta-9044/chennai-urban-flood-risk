"""IMD 0.25 deg gridded daily rainfall: file inspection and conversion helpers (pure Python/NumPy; netCDF4 or scipy for NetCDF).

Facts taken from IMD's own page (read 2026-11-22): 135 x 129 grid points; first record at 6.5N 66.5E, second at 6.5N 66.75E, last at 38.5N 100.0E;
yearly file with 365/366 daily records; unit mm; binary variant: 4-byte floats, south-to-north rows, GrADS UNDEF -999.0.
NOT stated by IMD's page (therefore inspected / provisional here): NetCDF variable and coordinate names, time encoding, missing-value attributes,
the day definition, and whether the grid points are cell centres. Nothing is resampled; missing values stay NaN."""
import re
from datetime import date, timedelta
import numpy as np
from rasterio.transform import Affine

NY, NX = 129, 135
RES = 0.25
LAT0, LON0 = 6.5, 66.5          # first grid point (from IMD's page)
LAT_LAST, LON_LAST = 38.5, 100.0
UNDEF = -999.0
RAIN_NAMES = ("rainfall", "rf", "rain", "precip", "precipitation", "pr", "tp")
DAY_DEFINITION = ("PROVISIONAL (unverified for this product): 24-h accumulation ending 08:30 IST on the labelled date; "
                  "the labelling convention (end date vs start date) is not confirmed")


def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def expected_grd_bytes(year):
    return (366 if is_leap(year) else 365) * NY * NX * 4


# ------------------------------------------------------------------ binary
def read_grd(path, year):
    """-> (cube days x NY x NX float32 with NaN for UNDEF, info). Verifies size exactly and picks the byte order whose values are sane."""
    raw = np.fromfile(path, dtype="u1")
    exp = expected_grd_bytes(year)
    if raw.size != exp:
        raise ValueError(f"{path}: {raw.size:,} bytes, expected exactly {exp:,} for {year} ({366 if is_leap(year) else 365} x {NY} x {NX} x 4)")
    best = None
    for order in ("<f4", ">f4"):
        a = raw.view(order).reshape(-1, NY, NX).astype("float32")
        fin = np.isfinite(a)
        sane = fin & ((a == UNDEF) | ((a >= 0) & (a < 2000)))
        score = float(sane.mean())
        if best is None or score > best[0]:
            best = (score, order, a)
    score, order, a = best
    if score < 0.999:
        raise ValueError(f"{path}: neither byte order gives plausible rainfall values (best {order}, {100 * score:.2f}% sane)")
    a = np.where(a == UNDEF, np.nan, a).astype("float32")
    return a, {"byte_order": order, "sane_fraction": score, "lat_first_south": True, "format": "grd"}


# ------------------------------------------------------------------ netcdf

def open_nc(path):
    """Read NetCDF variables into memory and close the file immediately.

    Returns:
        variables dict, global attributes dict, backend name.
    """
    try:
        import netCDF4

        ds = netCDF4.Dataset(path)
        try:
            ds.set_auto_maskandscale(False)
            vs = {}

            for n, v in ds.variables.items():
                arr = np.asarray(v[:]).copy()
                vs[n] = {
                    "dims": tuple(v.dimensions),
                    "attrs": {k: v.getncattr(k) for k in v.ncattrs()},
                    "shape": tuple(v.shape),
                    "dtype": str(v.dtype),
                    "data": lambda arr=arr: arr,
                }

            gattrs = {k: ds.getncattr(k) for k in ds.ncattrs()}

        finally:
            ds.close()

        return vs, gattrs, "netCDF4"

    except ImportError:
        pass

    from scipy.io import netcdf_file

    ds = netcdf_file(path, mmap=False)
    try:
        vs = {}

        for n, v in ds.variables.items():
            arr = np.array(v.data, copy=True)
            attrs = {
                k: (x.decode() if isinstance(x, bytes) else x)
                for k, x in v._attributes.items()
            }

            vs[n] = {
                "dims": tuple(v.dimensions),
                "attrs": attrs,
                "shape": tuple(v.shape),
                "dtype": str(arr.dtype),
                "data": lambda arr=arr: arr,
            }

        gattrs = {
            k: (x.decode() if isinstance(x, bytes) else x)
            for k, x in ds._attributes.items()
        }

    finally:
        ds.close()

    return vs, gattrs, "scipy-netcdf3"

def _find(vs, names, units=None, axis=None):
    for n, v in vs.items():
        a = v["attrs"]
        if n.lower() in names or str(a.get("standard_name", "")).lower() in names or str(a.get("axis", "")).upper() == (axis or "#"):
            return n
        if units and str(a.get("units", "")).lower() in units:
            return n
    return None


def inspect_nc(vs, gattrs):
    """Structured description used for configuration and the report (no assumptions beyond name matching, which is logged)."""
    rain = next((n for n, v in vs.items() if n.lower() in RAIN_NAMES and len(v["shape"]) == 3), None)
    if rain is None:
        c3 = [n for n, v in vs.items() if len(v["shape"]) == 3 and "float" in v["dtype"]]
        rain = c3[0] if len(c3) == 1 else None
    tname = _find(vs, ("time", "t", "valid_time"), axis="T")
    lat = _find(vs, ("lat", "latitude"), units=("degrees_north", "degree_north", "degrees_n"), axis="Y")
    lon = _find(vs, ("lon", "longitude"), units=("degrees_east", "degree_east", "degrees_e"), axis="X")
    return {"rain_var": rain, "time_var": tname, "lat_var": lat, "lon_var": lon, "variables": {n: {k: v[k] for k in ("dims", "shape", "dtype", "attrs")} for n, v in vs.items()},
            "global_attrs": gattrs}


_TIME_RE = re.compile(r"^\s*(days?|hours?|minutes?|seconds?)\s+since\s+(\d{4})-(\d{1,2})-(\d{1,2})", re.I)


def decode_time(values, units):
    """'days since YYYY-MM-DD[...]' (also hours/minutes/seconds) -> list of dates (whole days; fractional parts must be ~0 or a half-day label)."""
    m = _TIME_RE.match(str(units or ""))
    if not m:
        raise ValueError(f"unsupported/missing time units {units!r}: refusing to guess dates")
    unit, y, mo, d = m.group(1).lower(), int(m.group(2)), int(m.group(3)), int(m.group(4))
    f = {"d": 1.0, "h": 1 / 24, "m": 1 / 1440, "s": 1 / 86400}[unit[0]]
    base = date(y, mo, d)
    days = np.asarray(values, dtype="float64") * f
    return [base + timedelta(days=int(np.floor(x + 1e-6))) for x in days], days


def grid_from_coords(lat, lon, registration="centre"):
    """Check regularity and the IMD grid facts; return (flip_lat, transform north-up). registration='centre': coordinates are cell centres (PROVISIONAL)."""
    lat, lon = np.asarray(lat, dtype="float64"), np.asarray(lon, dtype="float64")
    if lat.size != NY or lon.size != NX:
        raise ValueError(f"grid is {lat.size} x {lon.size}, IMD documents {NY} x {NX}")
    dlat, dlon = np.diff(lat), np.diff(lon)
    if not (np.allclose(np.abs(dlat), RES, atol=1e-4) and np.allclose(np.abs(dlon), RES, atol=1e-4)):
        raise ValueError("coordinates are not a regular 0.25 deg grid")
    if not (dlon > 0).all():
        raise ValueError("longitude is not increasing; unsupported")
    asc = bool((dlat > 0).all())
    if not asc and not (dlat < 0).all():
        raise ValueError("latitude is not monotonic")
    lo, hi = (lat.min(), lat.max())
    if not (np.isclose(lo, LAT0, atol=1e-3) and np.isclose(hi, LAT_LAST, atol=1e-3) and np.isclose(lon.min(), LON0, atol=1e-3) and np.isclose(lon.max(), LON_LAST, atol=1e-3)):
        raise ValueError(f"extent lat {lo}..{hi}, lon {lon.min()}..{lon.max()} differs from IMD's documented 6.5-38.5N, 66.5-100.0E")
    half = RES / 2 if registration == "centre" else 0.0
    t = Affine(RES, 0, lon.min() - half, 0, -RES, hi + half)
    return asc, t       # asc=True means rows run south->north and must be flipped for a north-up raster


def cells_for_bounds(transform, shape, bounds_wgs84):
    """Native cell (row, col, centre lon, centre lat) pairs whose cell (not centre) overlaps the bounds - for manual cell inspection."""
    l, b, r, t = bounds_wgs84
    out = []
    for i in range(shape[0]):
        for j in range(shape[1]):
            x0, y1 = transform.c + j * transform.a, transform.f + i * transform.e
            x1, y0 = x0 + transform.a, y1 + transform.e
            if x0 < r and x1 > l and y0 < t and y1 > b:
                out.append((i, j, (x0 + x1) / 2, (y0 + y1) / 2))
    return out


def clean_values(a, attrs):
    """NaN for _FillValue/missing_value/UNDEF/non-finite. Negative or implausible values are NOT altered here (flagged by the workflow)."""
    a = np.asarray(a, dtype="float64")
    bad = ~np.isfinite(a)
    for k in ("_FillValue", "missing_value"):
        if k in attrs:
            vals = np.atleast_1d(attrs[k]).astype("float64")
            for v in vals:
                bad |= np.isclose(a, v, rtol=0, atol=1e-6 + 1e-6 * abs(v))
    bad |= a == UNDEF
    sf, ao = attrs.get("scale_factor"), attrs.get("add_offset")
    out = np.where(bad, np.nan, a)
    if sf is not None or ao is not None:
        out = out * float(1 if sf is None else sf) + float(0 if ao is None else ao)
    return out.astype("float32"), int(bad.sum())
