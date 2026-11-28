# Dashboard guide

## Launch

From the repository root on Windows:

```powershell
& ".\.venv\Scripts\python.exe" -m streamlit run dashboard\app.py
```

If the repository's launcher is available:

```powershell
.\run_dashboard.ps1
```

Stop Streamlit with `Ctrl+C` in the terminal running the app.

## Structure

- `dashboard/app.py` is the Streamlit entry point.
- `dashboard/lib/` contains shared dashboard helpers.
- `dashboard/sections/` contains section-level views.
- `dashboard/static/` contains static assets, including locally vendored map assets.
- `dashboard/legacy/` contains retained legacy code; do not assume it is the active entry point.

## Review checklist

1. Confirm the application starts without import/runtime errors.
2. Check that the intended Chennai extent and zoom limits are applied.
3. Check basemap and layer rendering, legends, units and classification labels.
4. Check opacity/visibility controls and section navigation.
5. Check map contrast and readability in light and dark themes where supported.
6. Check scale and north-arrow presentation.
7. Confirm unavailable layers are clearly represented as unavailable, not as zero.
8. Compare the running dashboard with the dated FINAL-02 screenshots.
9. Check that displayed evidence labels and scientific caveats remain visible.
10. Capture new screenshots only after a fresh, recorded visual check.

## Interpretation

The dashboard is a presentation layer. It does not convert candidate signals into confirmed flood observations, susceptibility into probability, or reported references into ground truth.

## Existing visual evidence

See `DASHBOARD_SCREENSHOTS.md` for the inventory and provenance of retained screenshots under `docs/final/` and `docs/final02/`.
