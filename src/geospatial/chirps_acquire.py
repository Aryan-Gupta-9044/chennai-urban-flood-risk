"""Resumable, verified acquisition of CHIRPS v3 DAILY_SAT native-grid daily rasters (two-band: precipitation with masked -> -9999, valid 0/1).

Pure logic, no Earth Engine import: the network step (`export_fn`) and the integrity step (`validator`) are injected, so everything here is unit-tested
on SYNTHETIC rasters with simulated failures. Rules: a failed date stays FAILED/MISSING and is reported - never filled with 0; a file is only kept if it
passes the validator; an existing valid file is never overwritten without force; the manifest is rewritten atomically after every date (resumable)."""
import hashlib
import io
import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from . import chirps

TAG = "chirps_v3_sat"
SOURCE_ID = "chirps_v3_daily"                 # directory / workflow source id; the product variant is DAILY_SAT (RNL would get its own id)
DOI = "10.15780/G2JQ0P"
ATTRIBUTION = ("Contains CHIRPS v3 (Climate Hazards Center, UC Santa Barbara) data, DAILY_SAT variant, used under CC BY 4.0 (conservative reading; the Earth Engine "
               "catalog lists it as public domain). Cite: Climate Hazards Center Infrared Precipitation with Stations version 3 (CHIRPS3) Data Repository, "
               f"doi:{DOI} (2025); Funk et al. (2026) Sci Data 13, 718, doi:10.1038/s41597-026-07096-4.")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tif_bytes_from_download(data):
    """Return the GeoTIFF bytes from an EE download body (some exports arrive zipped). Raises if it is not a GeoTIFF."""
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data)); names = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
        if len(names) != 1: raise RuntimeError(f"zip holds {len(names)} tif files: {z.namelist()}")
        data = z.read(names[0])
    if data[:4] not in (b"II*\x00", b"MM\x00*"):
        raise RuntimeError(f"download is not a GeoTIFF (first bytes {data[:60]!r})")
    return data


def raw_name(d):
    return f"{TAG}_{d:%Y%m%d}.tif"


def validate_raw(path, *, crs, native_tr, win_tr, shape, weights, touch):
    """Full local verification of one raw two-band raster against the native-grid and mask rules. Returns a JSON-safe dict:
    {problems: [...], info, aoi_area_coverage, cells_valid, cells_missing, zero_cells_valid, sentinel_cells, valid_min, valid_max}. Empty problems = accepted."""
    import rasterio
    out = {"problems": [], "info": {}}
    try:
        with rasterio.open(path) as ds:
            arr = ds.read(); dtf, dshape, dcrs = ds.transform, (ds.height, ds.width), ds.crs
            out["info"] = {"count": ds.count, "shape": [ds.height, ds.width], "dtype": ds.dtypes[0], "file_nodata_attr": ds.nodata, "crs": str(ds.crs),
                           "res": list(ds.res), "transform": list(ds.transform)[:6], "bounds": list(ds.bounds)}
    except Exception as e:                                   # noqa: BLE001
        out["problems"].append(f"unreadable GeoTIFF: {type(e).__name__}: {str(e)[:120]}"); return out
    if out["info"]["count"] != 2:
        out["problems"].append(f"{out['info']['count']} bands (expected 2: precipitation, valid)"); return out
    out["problems"] += chirps.check_export_grid(dtf, dshape, dcrs, win_tr, shape, native_tr, crs)
    if out["problems"]: return out
    out["problems"] += chirps.check_export(arr[0], arr[1])
    if out["problems"]: return out
    valid = arr[1] == 1
    cov = chirps.coverage(valid, weights)
    vals = arr[0][valid]
    out.update({"aoi_area_coverage": cov["aoi_area_coverage"], "cells_touching_aoi": cov["cells_touching_aoi"], "cells_valid": cov["cells_valid"], "cells_missing": cov["cells_missing"],
                "zero_cells_valid": int((vals == 0).sum()), "sentinel_cells": int((arr[0] == chirps.EXPORT_NODATA).sum()),
                "valid_min": float(vals.min()) if vals.size else None, "valid_max": float(vals.max()) if vals.size else None})
    return out


def load_manifest(path):
    try:
        m = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(m.get("entries"), dict): return m
    except Exception:                                        # noqa: BLE001
        pass
    return None


def save_manifest(path, manifest):
    path = Path(path); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(chirps.json_safe(manifest), indent=1), encoding="utf-8")
    os.replace(tmp, path)                                    # atomic: an interrupted run never leaves a half-written manifest


def classify(res, min_coverage):
    """Status for a file that PASSED integrity validation: OK, or LOW_COVERAGE when its AOI-area coverage is below the threshold. The data are valid and are
    RETAINED (inspection/resumability) but a LOW_COVERAGE date never counts as accepted for a complete acquisition."""
    return "OK" if res["aoi_area_coverage"] >= min_coverage else "LOW_COVERAGE"


def acquire(dates, raw_dir, export_fn, validator, manifest_path, *, header=None, retries=4, backoff=2.0, sleep=time.sleep, force=False, log=print, min_coverage=0.95):
    """For each date: keep/adopt an existing VALID file, else download (<= retries attempts with exponential backoff), validate, and record.
    export_fn(d, tmp_path) -> {'http_status', 'content_type', 'request_params', 'url_host'}; must write a file at tmp_path or raise.
    validator(d, path) -> dict with 'problems' (list, empty = ok). Returns the manifest. Never writes a placeholder/zero raster."""
    raw_dir = Path(raw_dir); (raw_dir / "failed").mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path) or {"entries": {}}
    manifest.update(header or {})
    manifest["min_coverage"] = min_coverage
    manifest["last_run_utc"] = utcnow()
    for d in dates:
        key = d.isoformat(); dest = raw_dir / raw_name(d); ent = manifest["entries"].get(key, {}); ent = dict(ent) if ent else {}
        ent.update({"date": key, "file": dest.name})
        ent.setdefault("attempts", [])
        # ---- 1. existing file
        if dest.exists() and not force:
            res = validator(d, dest)
            sha = sha256_file(dest)
            if not res["problems"]:
                st = classify(res, min_coverage)
                same = ent.get("sha256") == sha and ent.get("status") == st
                ent.update(status=st, sha256=sha, bytes=dest.stat().st_size, validation=res,
                           provenance=("resumed: file and manifest checksum agree; re-validated" if same else "adopted existing file (not recorded in manifest or checksum differs); re-validated, original download request not captured"))
                manifest["entries"][key] = ent; save_manifest(manifest_path, manifest); log(f"[{key}] kept existing valid file"); continue
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            shutil.move(str(dest), str(raw_dir / "failed" / f"{dest.name}.{stamp}.invalid"))
            ent["attempts"].append({"n": 0, "utc": utcnow(), "outcome": "existing file failed validation and was moved to failed/", "problems": res["problems"]})
            log(f"[{key}] existing file invalid -> moved to failed/: {res['problems']}")
        # ---- 2. download with retries
        ok = False; last = None
        for n in range(1, retries + 1):
            tmp = raw_dir / f".{dest.name}.part"
            try:
                if tmp.exists(): tmp.unlink()
                meta = export_fn(d, tmp)
                res = validator(d, tmp)
                if res["problems"]:
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                    shutil.move(str(tmp), str(raw_dir / "failed" / f"{dest.name}.{stamp}.a{n}.invalid"))
                    last = "validation failed: " + "; ".join(res["problems"])
                    ent["attempts"].append({"n": n, "utc": utcnow(), "outcome": "validation failed", "problems": res["problems"]})
                else:
                    os.replace(tmp, dest)
                    ent.update(status=classify(res, min_coverage), sha256=sha256_file(dest), bytes=dest.stat().st_size, retrieved_utc=utcnow(), http_status=meta.get("http_status"),
                               content_type=meta.get("content_type"), request_params=meta.get("request_params"), request_url_host=meta.get("url_host"),
                               validation=res, provenance="downloaded this run (Earth Engine getDownloadURL, native grid window)")
                    ent["attempts"].append({"n": n, "utc": utcnow(), "outcome": "ok"})
                    ok = True; break
            except KeyboardInterrupt:
                manifest["entries"][key] = ent; save_manifest(manifest_path, manifest); raise
            except Exception as e:                           # noqa: BLE001
                last = f"{type(e).__name__}: {str(e)[:200]}"
                ent["attempts"].append({"n": n, "utc": utcnow(), "outcome": "error", "error": last})
                if tmp.exists(): tmp.unlink()
            if n < retries: sleep(backoff * (2 ** (n - 1)))
        if not ok:
            ent.update(status="FAILED", last_error=last, sha256=None, bytes=None)
            log(f"[{key}] FAILED after {retries} attempt(s): {last}")
        else:
            log(f"[{key}] {ent['status']}  cov={ent['validation']['aoi_area_coverage']:.1%} (min {min_coverage:.0%}) valid cells={ent['validation']['cells_valid']}/{ent['validation']['cells_touching_aoi']}")
        manifest["entries"][key] = ent; save_manifest(manifest_path, manifest)
    return manifest


def summarize(manifest, dates, min_coverage=None):
    """ok = integrity AND coverage passed (status OK). low_coverage = valid files below the threshold (retained, NOT accepted). failed_or_missing = no accepted
    raster. complete is True ONLY if every expected date is OK. min_coverage (if given) re-checks recorded coverage against that threshold."""
    ents = manifest["entries"]; ok, low, failed = [], [], []
    for d in dates:
        e = ents.get(d.isoformat(), {}); st = e.get("status")
        if st in ("OK", "LOW_COVERAGE") and min_coverage is not None:
            st = "OK" if e["validation"]["aoi_area_coverage"] >= min_coverage else "LOW_COVERAGE"
        (ok if st == "OK" else low if st == "LOW_COVERAGE" else failed).append(d)
    return {"expected": len(dates), "ok": len(ok), "failed_or_missing": [d.isoformat() for d in failed], "low_coverage": [d.isoformat() for d in low],
            "below_min_coverage": [d.isoformat() for d in low], "complete": len(ok) == len(dates) and len(dates) > 0}
