"""Ward boundary acquisition. Order: user file in data/external/wards -> cached raw -> DataMeet GitHub."""
import json
from pathlib import Path
from ..utils import net
from ..utils.paths import DATA_EXT, DATA_RAW, external_kind
from ..geospatial.vector_io import find_vector_files, VECTOR_EXT

RAW_DIR = DATA_RAW / "wards"
EXT_PRIORITY = {".geojson": 0, ".json": 1, ".gpkg": 2, ".shp": 3, ".zip": 4}


def _choose(entries):
    """entries: list of dicts with name/download_url. Prefer files with 'ward' in the name."""
    cands = [e for e in entries if Path(e["name"]).suffix.lower() in EXT_PRIORITY]
    cands.sort(key=lambda e: ("ward" not in e["name"].lower(), EXT_PRIORITY[Path(e["name"]).suffix.lower()], e["name"]))
    return cands


def _list_github(api_url, log, depth=1):
    items = net.get_json(api_url)
    files = []
    for it in items:
        if it.get("type") == "file":
            files.append(it)
        elif it.get("type") == "dir" and depth > 0:
            try:
                files.extend(_list_github(it["url"], log, depth - 1))
            except Exception as e:
                log.warning("could not list %s: %s", it.get("name"), e)
    return files


def acquire_wards(settings, log):
    """Returns (path, provenance dict) or (None, {'error': ...})."""
    ext = find_vector_files(DATA_EXT / "wards")
    if ext:
        log.info("using user-supplied ward file: %s", ext[0])
        return ext[0], {"kind": external_kind(), "source": f"data/external/wards/{ext[0].name}"}

    cached = find_vector_files(RAW_DIR)
    if cached:
        log.info("using cached raw ward file: %s", cached[0].name)
        meta = RAW_DIR / "source.json"
        src = json.loads(meta.read_text()) if meta.exists() else {"source": "cached raw download"}
        return cached[0], {"kind": "REAL", **src}

    w = settings["wards"]
    errors = []
    try:
        files = _list_github(w["github_api"], log)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / "github_listing.json").write_text(json.dumps([f["name"] for f in files], indent=2))
        log.info("GitHub listing: %s", [f["name"] for f in files])
        cands = _choose(files)
        if not cands:
            errors.append("GitHub directory listed but contains no vector file (see data/raw/wards/github_listing.json)")
        else:
            pick = cands[0]
            stem = Path(pick["name"]).stem
            to_get = [pick]
            if pick["name"].lower().endswith(".shp"):
                to_get += [f for f in files if Path(f["name"]).stem == stem and not f["name"].lower().endswith(".shp")
                           and Path(f["name"]).suffix.lower() in (".dbf", ".shx", ".prj", ".cpg")]
            for f in to_get:
                net.download(f["download_url"], RAW_DIR / f["name"], log=log)
            path = RAW_DIR / pick["name"]
            src = {"source": f"DataMeet Municipal_Spatial_Data / Chennai / {pick['name']}",
                   "url": pick["download_url"]}
            (RAW_DIR / "source.json").write_text(json.dumps(src, indent=2))
            return path, {"kind": "REAL", **src}
    except Exception as e:
        errors.append(f"GitHub listing failed: {str(e)[:200]}")
        log.warning(errors[-1])

    for name in w.get("guess_files", []):
        try:
            p = net.download(w["raw_base"] + name, RAW_DIR / name, retries=1, log=log)
            src = {"source": f"DataMeet raw file {name}", "url": w["raw_base"] + name}
            (RAW_DIR / "source.json").write_text(json.dumps(src, indent=2))
            return p, {"kind": "REAL", **src}
        except Exception as e:
            errors.append(f"{name}: {str(e)[:120]}")
    return None, {"error": " | ".join(errors) or "no source reachable"}
