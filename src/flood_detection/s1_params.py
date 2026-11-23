import hashlib
import json
from ..utils import paths

NODATA = -9999.0


def load_events():
    return json.loads((paths.CONFIG / "s1_events.json").read_text(encoding="utf-8"))


def _coerce(v):
    s = str(v).strip()
    if s.lower() in ("none", "null"):
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s) if s.lstrip("-").isdigit() else float(s)
    except ValueError:
        return s


def get_params(overrides=None):
    cfg = load_events()["s1b_params"]
    p = {k: v for k, v in cfg.items() if not k.startswith("_")}
    for k, v in (overrides or {}).items():
        if k not in p:
            raise KeyError(f"unknown parameter '{k}'. Valid: {sorted(p)}")
        p[k] = _coerce(v)
    return p


def run_id(event_id, scene_ids, params, grid):
    blob = json.dumps({"event": event_id, "scenes": scene_ids, "params": params, "grid": [grid.crs, list(grid.transform)[:6], grid.shape]},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]
