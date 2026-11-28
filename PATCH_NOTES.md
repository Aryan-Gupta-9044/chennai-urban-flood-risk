# Rainfall workflow Sentinel-1 date-source fix (v1)

## Files
- `scripts/rainfall_workflow.py`
- `tests/test_rainfall.py`

## Correction
The rainfall event's existing `sentinel1_dates_from` setting now selects the Sentinel-1 date source:
- `2015_nov_dec` continues to read `config/s1_candidate_roles.json`, preserving its eight existing dates and categories.
- `2021_sep_nov` reads the eight dates from `config/s1_preprocess.json`. The antecedent CSV category is `unassigned`; these dates are processed-observation dates, not dry/flood/baseline labels.
- The plot legend and report now identify processed-observation dates accurately.
- Invalid, duplicate, or out-of-context dates block the workflow instead of silently producing misleading antecedent rows.

The patch also fixes the rainfall workflow's output-file registry and report log to use the actual `--outputs-dir`, rather than hard-coded `outputs/...` paths. It does not change the rainfall event configs, Sentinel-1 configs, CHIRPS data, 2015 candidate roles, or existing outputs.

## Apply
From the project root, back up the two target files, then extract this ZIP into the project root with overwrite enabled. Do not run `git clean`, `git reset`, or delete output folders.

## Verify
Run:
```powershell
python -m pytest tests/test_rainfall.py -q
python -m pytest tests/test_chirps_2021_isolation.py tests/test_chirps_acquire.py -q
python -m pytest -q
```

Only after tests pass, rerun the 2021 rainfall workflow with the same arguments as the previous run and continue suppressing the shared `outputs/reports/status.json` write as before. No Earth Engine request or data download is required.
