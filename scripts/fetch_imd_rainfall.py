#!/usr/bin/env python
"""Module IMD (V2.3 demo) - obtain / register the OFFICIAL IMD 0.25 deg yearly rainfall file and record provenance.
Never silently switches source. The original file is preserved under data/external/rainfall/imd_gridded_daily/raw/ and never overwritten without --force.

What is verified and what is not (read the output):
  * IMD's page (imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html) shows a year selector but does not expose its form action.
  * The BINARY endpoint below (POST rain=<year> to .../cmpg/Griddata/rainfall.php) is the one used by the third-party client `imdlib`; it is NOT documented on IMD's page.
  * For NetCDF no endpoint is known to me: download it in a browser from the IMD page and register it with --register, or pass --url/--field if you read them from the page's form.
Usage (PowerShell, project folder):
  .\\.venv\\Scripts\\python scripts\\fetch_imd_rainfall.py --year 2015 --format grd
  .\\.venv\\Scripts\\python scripts\\fetch_imd_rainfall.py --year 2015 --format nc --register C:\\Users\\you\\Downloads\\<file>.nc"""
import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils import status, paths
from src.utils.logging_setup import get_logger
from src.geospatial import imd

BASE = paths.DATA_EXT / "rainfall" / "imd_gridded_daily"
RAW = BASE / "raw"
GRD_URL = "https://imdpune.gov.in/cmpg/Griddata/rainfall.php"
PAGES = {"nc": "https://imdpune.gov.in/cmpg/Griddata/Rainfall_25_NetCDF.html", "grd": "https://imdpune.gov.in/cmpg/Griddata/Rainfall_25_Bin.html"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def validate(path, fmt, year):
    """-> (ok, problems, details). Checks size, signature and readability. Does not judge scientific content."""
    problems, det = [], {"size_bytes": Path(path).stat().st_size}
    head = Path(path).read_bytes()[:8]
    if det["size_bytes"] == 0:
        return False, ["empty file (IMD signals 'not available' with an empty reply)"], det
    if head[:1] == b"<" or head.lower().startswith(b"<!doc") or head.lower().startswith(b"<html"):
        return False, ["response is HTML, not a data file"], det
    if fmt == "grd":
        exp = imd.expected_grd_bytes(year)
        if det["size_bytes"] != exp:
            problems.append(f"size {det['size_bytes']:,} != expected {exp:,}")
        else:
            try:
                _, info = imd.read_grd(path, year); det.update(info)
            except ValueError as e:
                problems.append(str(e))
    else:
        det["file_signature"] = "netcdf3" if head[:3] == b"CDF" else "netcdf4/hdf5" if head[:4] == b"\x89HDF" else "UNKNOWN"
        if det["file_signature"] == "UNKNOWN":
            problems.append(f"not a NetCDF file (first bytes {head!r})")
        else:
            try:
                vs, ga, backend = imd.open_nc(path); inf = imd.inspect_nc(vs, ga)
                det.update(backend=backend, rain_var=inf["rain_var"], time_var=inf["time_var"], lat_var=inf["lat_var"], lon_var=inf["lon_var"])
            except Exception as e:  # noqa
                problems.append(f"NetCDF not readable: {str(e)[:200]}")
    return (not problems), problems, det


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2015)
    ap.add_argument("--format", choices=["grd", "nc"], default="grd")
    ap.add_argument("--register", default="", help="path of a file you downloaded manually from the IMD page")
    ap.add_argument("--url", default="", help="override the POST/GET endpoint (needed for nc)")
    ap.add_argument("--field", default="rain", help="form field name carrying the year")
    ap.add_argument("--method", choices=["POST", "GET"], default="POST")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t0 = time.time(); log = get_logger("IMD_fetch"); paths.ensure_dirs(); RAW.mkdir(parents=True, exist_ok=True)
    ext = "grd" if a.format == "grd" else "nc"
    final = RAW / f"imd_rain_0p25_{a.year}.{ext}"
    man = RAW / f"imd_rain_0p25_{a.year}.{ext}.manifest.json"
    if final.exists() and not a.force:
        log.info("original already preserved: %s (use --force to replace; the old file is kept as .bak)", final)
        ok, pr, det = validate(final, a.format, a.year)
        status.record("IMD", status.COMPLETED if ok else status.BLOCKED, f"raw file present: {final.name}; validation {'OK' if ok else pr}", files=[paths.rel(final)], seconds=time.time() - t0)
        return
    tmp = RAW / f".incoming_{a.year}.{ext}"
    manifest = {"product": "IMD gridded daily rainfall 0.25 deg (Pai et al. 2014)", "year": a.year, "format": a.format, "official_page": PAGES[a.format],
                "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if a.register:
        src = Path(a.register)
        if not src.exists():
            msg = f"file not found: {src}"; log.error(msg); status.record("IMD", status.BLOCKED, msg, seconds=time.time() - t0); return
        shutil.copyfile(src, tmp)
        manifest.update(method="manual browser download from the official IMD page, registered with --register", source_url=PAGES[a.format], original_name=src.name)
    else:
        url = a.url or (GRD_URL if a.format == "grd" else "")
        if not url:
            msg = ("No NetCDF endpoint is known: IMD's page does not expose it. Download the 2015 NetCDF in a browser from " + PAGES["nc"] +
                   " (select 2015, press the button), then run this script again with --register <downloaded file>. Alternatively use --format grd (binary).")
            log.error(msg); status.record("IMD", status.BLOCKED, msg, requirements=["manual browser download or --url/--field"], seconds=time.time() - t0); return
        import requests
        log.info("%s %s year=%s ...", a.method, url, a.year)
        try:
            r = requests.request(a.method, url, **({"data": {a.field: a.year}} if a.method == "POST" else {"params": {a.field: a.year}}), timeout=300)
        except Exception as e:  # noqa
            msg = f"request failed: {type(e).__name__}: {str(e)[:250]}. No other source was tried."
            log.error(msg); status.record("IMD", status.BLOCKED, msg, requirements=["network access to imdpune.gov.in, or --register a manually downloaded file"], seconds=time.time() - t0); return
        manifest.update(method=f"{a.method} {url} {a.field}={a.year}", source_url=url, http_status=r.status_code, content_type=r.headers.get("Content-Type"),
                        content_length_header=r.headers.get("Content-Length"), endpoint_note="endpoint taken from third-party client imdlib; not documented on IMD's page" if url == GRD_URL else "user-supplied endpoint")
        log.info("HTTP %s, content-type %s, %s bytes", r.status_code, r.headers.get("Content-Type"), f"{len(r.content):,}")
        if r.status_code != 200:
            msg = f"HTTP {r.status_code} from {url}"; log.error(msg); status.record("IMD", status.BLOCKED, msg, seconds=time.time() - t0); return
        tmp.write_bytes(r.content)
    ok, problems, det = validate(tmp, a.format, a.year)
    manifest.update(validation_ok=ok, validation_problems=problems, validation_details=det)
    if not ok:
        bad = RAW / "failed"; bad.mkdir(exist_ok=True)
        keep = bad / f"failed_{a.year}_{datetime.now():%Y%m%d_%H%M%S}.bin"; shutil.move(tmp, keep)
        manifest["failed_response_saved_as"] = paths.rel(keep)
        (bad / (keep.name + ".json")).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        msg = "downloaded file FAILED validation: " + "; ".join(problems)
        log.error(msg); status.record("IMD", status.BLOCKED, msg, seconds=time.time() - t0); return
    if final.exists():
        final.rename(final.with_suffix(final.suffix + f".bak-{datetime.now():%Y%m%d%H%M%S}"))
    shutil.move(tmp, final)
    manifest.update(file=paths.rel(final), size_bytes=final.stat().st_size, sha256=sha256(final))
    man.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("saved %s (%s bytes, sha256 %s...)", paths.rel(final), f"{manifest['size_bytes']:,}", manifest["sha256"][:16])
    status.record("IMD", status.COMPLETED, f"IMD {a.year} {a.format} obtained and validated: {final.name}, {manifest['size_bytes']:,} bytes. Provenance in {man.name}.",
                  files=[paths.rel(final), paths.rel(man)], seconds=time.time() - t0)


if __name__ == "__main__":
    main()
