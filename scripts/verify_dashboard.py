#!/usr/bin/env python
"""Module H - run the dashboard headlessly (Streamlit AppTest) and record whether it renders without exceptions."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils import status, paths
from src.utils.logging_setup import get_logger


def main():
    t0 = time.time()
    log = get_logger("H_dashboard")
    app = paths.ROOT / "dashboard" / "app.py"
    try:
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(app), default_timeout=120).run()
        errs = [str(e.value) for e in at.exception]
        if errs:
            raise RuntimeError("; ".join(errs)[:400])
        n_tabs = len(at.tabs)
        msg = (f"Dashboard renders headlessly with no exceptions ({n_tabs} tabs). "
               "Start it with:  .\\.venv\\Scripts\\streamlit run dashboard\\app.py")
        status.record("H", status.COMPLETED, msg, files=["dashboard/app.py"], seconds=time.time() - t0)
        log.info(msg)
    except Exception as e:
        log.error("dashboard check failed: %s", e)
        status.record("H", status.BLOCKED, f"Dashboard check failed: {str(e)[:300]}", files=["dashboard/app.py"],
                      seconds=time.time() - t0)


if __name__ == "__main__":
    main()
