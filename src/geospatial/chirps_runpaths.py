"""Run-path isolation for the CHIRPS probe / acquisition / preparation scripts (V2.3, 2021 context).

The 2015 run uses the DEFAULT locations (data/external/rainfall/chirps_v3_daily, outputs/) and status ids CH3 / CH3A / CH3P. A run for any OTHER event must
use its own base/outputs directories and its own status id, and must never resolve into (or contain) the default 2015 locations. `resolve_run_paths` enforces that
before anything is written. Pure path logic: no Earth Engine, no file writes."""
import hashlib
import json
from pathlib import Path
from src.utils import paths

DEFAULT_EVENT = "2015_nov_dec"
DEFAULT_SOURCE_ID = "chirps_v3_daily"
DEFAULT_STATUS = {"probe": "CH3", "acquire": "CH3A", "prepare": "CH3P"}


class PathIsolationError(RuntimeError):
    """A non-default event was pointed at the default (2015) directories or status ids."""


def default_base():
    return paths.DATA_EXT / "rainfall" / DEFAULT_SOURCE_ID


def default_outputs():
    return paths.ROOT / "outputs"


PROTECTED_STATUS_IDS = frozenset(DEFAULT_STATUS.values())      # CH3, CH3A, CH3P: reserved for the 2015 run whatever script is used


def protected_output_dirs():
    """The 2015 evidence locations under the default outputs root. A sibling such as outputs/chirps_2021 is NOT protected (its own reports/tables/figures live below it)."""
    o = default_outputs(); return [o, o / "reports", o / "tables", o / "figures"]


def _outputs_conflict(outd):
    """True if `outd` equals/contains the default outputs root, or equals/lies inside outputs/reports|tables|figures. A run writes <outd>/reports|tables|figures, so
    any other directory (even one inside outputs/) cannot touch the 2015 files."""
    outd = _res(outd); o = default_outputs()
    if outd == o or outd in o.parents: return True
    return any(outd == d or d in outd.parents for d in protected_output_dirs()[1:])


def _res(p):
    return Path(p).expanduser().resolve()


def _overlap(a, b):
    a, b = _res(a), _res(b)
    return a == b or a in b.parents or b in a.parents


def resolve_run_paths(kind, event, base_dir=None, outputs_dir=None, status_id=None):
    """Return {'base','outputs','tables','reports','figures','status_id'} for a run. `kind` is probe | acquire | prepare.
    Defaults (base_dir/outputs_dir/status_id None) reproduce the 2015 locations exactly. For event != DEFAULT_EVENT, a base/outputs directory that is the default one
    or overlaps it (either direction), or the default status id, raises PathIsolationError."""
    if kind not in DEFAULT_STATUS: raise ValueError(f"unknown kind {kind!r}")
    base = _res(base_dir) if base_dir else default_base(); outd = _res(outputs_dir) if outputs_dir else default_outputs(); sid = status_id or DEFAULT_STATUS[kind]
    if event != DEFAULT_EVENT:
        problems = []
        if base_dir is None or _overlap(base, default_base()): problems.append(f"--base-dir {base} is (or overlaps) the 2015 data directory {default_base()}")
        if outputs_dir is None: problems.append("--outputs-dir is required for a non-2015 event (e.g. outputs/chirps_2021)")
        elif _outputs_conflict(outd): problems.append(f"--outputs-dir {outd} is, contains or lies inside the protected 2015 output locations {[str(x) for x in protected_output_dirs()]}")
        if sid in PROTECTED_STATUS_IDS: problems.append(f"status id {sid!r} is a 2015 registry entry ({sorted(PROTECTED_STATUS_IDS)} are reserved); pass a distinct --status-id (e.g. {DEFAULT_STATUS[kind]}_2021)")
        if problems: raise PathIsolationError(f"event {event!r} must not write into the 2015 locations: " + "; ".join(problems))
    return {"base": base, "outputs": outd, "tables": outd / "tables", "reports": outd / "reports", "figures": outd / "figures", "status_id": sid}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


# --- 2015 preservation evidence ---------------------------------------------------------------------------------------------------------------
def protected_2015_files(root=None):
    """Every existing file belonging to the 2015 CHIRPS evidence, by glob (relative posix paths -> absolute Path). Sorted, deterministic."""
    root = Path(root) if root else paths.ROOT; out = {}
    pats = ["data/external/rainfall/chirps_v3_daily/**/*", "outputs/reports/chirps_v3_sat_probe*", "outputs/tables/chirps_v3_sat_probe*", "outputs/figures/chirps_v3_sat_probe_cells.png",
            "outputs/reports/chirps_v3_sat_acquisition*", "outputs/tables/chirps_v3_sat_acquisition*", "outputs/reports/chirps_v3_sat_preparation*", "outputs/tables/chirps_v3_sat_conversion*"]
    for pat in pats:
        for p in sorted(root.glob(pat)):
            if p.is_file(): out[p.relative_to(root).as_posix()] = p
    return dict(sorted(out.items()))


def snapshot(root=None):
    return {k: sha256_file(p) for k, p in protected_2015_files(root).items()}


def compare(before, after):
    """Return {'unchanged': n, 'modified': [...], 'deleted': [...], 'added': [...]}. `added` is informational (new files are not a violation); modified/deleted are."""
    mod = sorted(k for k in before if k in after and before[k] != after[k]); dele = sorted(k for k in before if k not in after); add = sorted(k for k in after if k not in before)
    return {"unchanged": sum(1 for k in before if k in after and before[k] == after[k]), "modified": mod, "deleted": dele, "added": add}


def save_snapshot(path, snap):
    Path(path).write_text(json.dumps({"files": snap}, indent=1, sort_keys=True), encoding="utf-8")


def load_snapshot(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["files"]


def probe_cache_reusable(cj, start, end, ncell, crs, n_expected):
    """True only if a saved probe server-per-date cache matches THIS window, AOI-cell count, CRS and date count (never reused across windows/grids)."""
    try:
        return bool(isinstance(cj, dict) and cj.get("window") == [start, end] and cj.get("cells_touching_aoi") == int(ncell) and cj.get("crs") == crs and len(cj.get("per_date", {})) == int(n_expected))
    except Exception:                                        # noqa: BLE001
        return False


def aoi_fingerprint(geom, grid_size=1e-9):
    """SHA-256 (first 16 hex) of the AOI geometry in the grid CRS after snapping to `grid_size` (so float noise below it does not change it)."""
    import shapely
    g = shapely.set_precision(geom, grid_size); return hashlib.sha256(shapely.to_wkb(shapely.normalize(g))).hexdigest()[:16]


def weights_fingerprint(weights, ndigits=10):
    """SHA-256 (first 16 hex) of the AOI area-weight raster: shape + values rounded to `ndigits`."""
    import numpy as np
    w = np.round(np.asarray(weights, dtype="float64"), ndigits) + 0.0; return hashlib.sha256(str(w.shape).encode() + w.tobytes()).hexdigest()[:16]


def probe_cache_matches(cj, start, end, ncell, crs, n_expected, aoi_fp, weights_fp):
    """probe_cache_reusable AND both fingerprints present in the cache and equal to the current ones. Caches written before the fingerprints existed are NOT reused."""
    if not probe_cache_reusable(cj, start, end, ncell, crs, n_expected): return False
    return bool(aoi_fp and weights_fp and cj.get("aoi_fingerprint") == aoi_fp and cj.get("weights_fingerprint") == weights_fp)
