"""Shared helpers for DEP-2 (reference evidence, exposure, vulnerability).

Everything here is deterministic and Windows-compatible (pathlib only, no shell calls).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ANALYSIS_CRS = "EPSG:32644"   # project analysis CRS (UTM 44N), same as SUS-1
GEO_CRS = "EPSG:4326"
VERSION = "DEP2-0.1"

LOG = logging.getLogger("dep2")


def setup_logging(log_file: Path | None = None, level=logging.INFO):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    root = logging.getLogger("dep2")
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    return root


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def write_json(p: Path, obj) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    return p


def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return None if not math.isfinite(float(o)) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
    except ImportError:  # pragma: no cover
        pass
    if isinstance(o, Path):
        return o.as_posix()
    return str(o)


def read_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def environment() -> dict:
    mods = {}
    for m in ("numpy", "pandas", "geopandas", "shapely", "pyproj", "rasterio", "pyogrio", "matplotlib", "pdfplumber", "scipy"):
        try:
            mods[m] = __import__(m).__version__
        except Exception:  # noqa: BLE001
            mods[m] = None
    return {"python": sys.version.split()[0], "platform": platform.platform(), "packages": mods}


def write_csv(df, p: Path, **kw) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, lineterminator="\n", **kw)
    return p


def write_gpkg(gdf, p: Path, layer: str) -> Path:
    """Write one layer; the file is replaced only inside the DEP-2 output tree."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.unlink()
    gdf.to_file(p, layer=layer, driver="GPKG")
    return p


def manifest(root: Path, out: Path, exclude=("SHA256SUMS.txt",)) -> int:
    root = Path(root)
    files = sorted(q for q in root.rglob("*") if q.is_file() and q.name not in exclude and "logs" not in q.relative_to(root).parts)  # logs grow after hashing
    lines = [f"{sha256_file(q)}  {q.relative_to(root).as_posix()}" for q in files]
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def guard_output_dir(out: Path, protected: list[Path]):
    """Refuse to write into any protected (accepted) output directory."""
    out = Path(out).resolve()
    for p in protected:
        p = Path(p).resolve()
        if out == p or p in out.parents or out in p.parents:
            raise SystemExit(f"STOP: output directory {out} overlaps protected path {p}")
