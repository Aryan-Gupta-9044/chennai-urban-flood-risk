import logging
import sys
from .paths import LOGS, ensure_dirs


def get_logger(name):
    """Logger that writes to console, logs/<name>.log and the shared logs/pipeline.log."""
    ensure_dirs()
    lg = logging.getLogger(name)
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [" + name + "] %(message)s", "%H:%M:%S")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOGS / f"{name}.log", encoding="utf-8"),
              logging.FileHandler(LOGS / "pipeline.log", encoding="utf-8")):
        h.setFormatter(fmt)
        lg.addHandler(h)
    lg.propagate = False
    return lg
