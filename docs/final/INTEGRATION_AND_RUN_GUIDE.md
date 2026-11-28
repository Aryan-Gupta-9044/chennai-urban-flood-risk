# Integration and run guide: FINAL-01 overlay (Windows)

This guide applies the FINAL-01 overlay package to the existing project folder on the Windows development machine. It then rebuilds the exploratory analytics, runs the tests and starts the unified dashboard.

- Project root: `C:\Users\aryan\Downloads\chennai-flood-risk-v2.3-dev\chennai-flood-risk`
- Python: `.\.venv\Scripts\python.exe`

## 0. What the overlay contains

The overlay holds only **new or changed** files. It never replaces accepted outputs. The full list with SHA-256 values is in `PACKAGE_SHA256SUMS.txt`.

| Path | State | Purpose |
|---|---|---|
| `dashboard/app.py` | changed | Unified dashboard v1: 11 sections, A to K |
| `dashboard/legacy/app_v0_initial.py` | new | Verbatim copy of the original `app.py` (sha256 `ecda30d8…`) |
| `dashboard/lib/`, `dashboard/sections/` | new | Registry, UI, maps, data access and section pages |
| `dashboard/static/vendor/` | new | Leaflet, jQuery and d3 from npm, so maps work offline |
| `src/analytics/` | new | ML-EXP-1: ward features, exploratory analysis, presence-background evaluation |
| `scripts/build_ward_analytics.py` | new | Builds `outputs/ml_exploratory_v1` |
| `scripts/run_pipeline.py` | changed | Module G (legacy RF v0) is skipped unless `CHENNAI_ALLOW_LEGACY_RF=1` |
| `scripts/_legacy/run_pipeline_v0_before_rf_gate.py` | new | Verbatim copy of the previous `run_pipeline.py` |
| `tests/test_ml_exp1.py`, `tests/test_dashboard_unified.py` | new | 26 tests |
| `outputs/ml_exploratory_v1/` | new | Analysis outputs (tables, figures, summary, SHA256SUMS) |
| `paper/` | new | IEEE conference-paper candidate (LaTeX source and PDF) |
| `docs/final/` | new | This guide, status report, evidence log, RF retirement note, Agent 1 questions, inventory |
| `requirements-dashboard.txt` | new | Dashboard dependencies |
| `run_dashboard.ps1` | new | Starts the dashboard |

`scripts/train_random_forest.py` is **unchanged**.

## 1. Back up and verify (PowerShell)

```powershell
cd C:\Users\aryan\Downloads\chennai-flood-risk-v2.3-dev
Get-FileHash .\CHENNAI_FINAL01_OVERLAY_*.zip -Algorithm SHA256   # compare with the hash in the delivery message
Copy-Item chennai-flood-risk\dashboard\app.py chennai-flood-risk\dashboard\app_before_final01.py
Copy-Item chennai-flood-risk\scripts\run_pipeline.py chennai-flood-risk\scripts\run_pipeline_before_final01.py
```

## 2. Extract the overlay into a staging folder, then copy it in

```powershell
Expand-Archive .\CHENNAI_FINAL01_OVERLAY_*.zip -DestinationPath .\final01_staging
# Dry run: list files that already exist and would be replaced (should be only app.py and run_pipeline.py)
Get-ChildItem .\final01_staging\overlay -Recurse -File | ForEach-Object {
  $rel = $_.FullName.Substring((Resolve-Path .\final01_staging\overlay).Path.Length + 1)
  if (Test-Path (Join-Path .\chennai-flood-risk $rel)) { "EXISTS: $rel" } }
robocopy .\final01_staging\overlay .\chennai-flood-risk /E /XO /NFL /NDL
```

If the dry run lists anything other than `dashboard\app.py` and `scripts\run_pipeline.py`, stop and report it.

`robocopy /XO` does not overwrite files that are newer than the overlay copy. If you have edited `app.py` or `run_pipeline.py` locally since 28 Nov, compare them first.

## 3. Install the dashboard dependencies

```powershell
cd chennai-flood-risk
.\.venv\Scripts\python.exe -m pip install -r requirements-dashboard.txt
```

Tested with streamlit 1.67.0, folium 1.0.0 and altair 6.3.0. Streamlit 1.30 or later works; the code chooses the correct `width` argument for the installed version.

## 4. Verify the overlay

```powershell
.\.venv\Scripts\python.exe scripts\verify_final01_overlay.py
```

This checks every file in `docs\final\PACKAGE_SHA256SUMS.txt`.

## 5. (Optional) Rebuild the exploratory analytics

The outputs are already in the overlay. Rebuild only to confirm reproducibility:

```powershell
.\.venv\Scripts\python.exe scripts\build_ward_analytics.py --outdir outputs\ml_exploratory_v1_rerun
```

- The full run takes about 8 minutes. Add `--quick` for a run of about 1 minute with fewer permutations.
- The script hash-checks its inputs before and after the run, and exits with code 2 if any input changed.
- Do not write into `outputs\ml_exploratory_v1` itself. The script refuses protected output folders.

## 6. Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ml_exp1.py tests\test_dashboard_unified.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Sandbox results on the merged PART1–3 repository with the overlay applied are in `FINAL_STATUS_REPORT.md`.

- On Windows with `earthengine-api` installed, `test_import_src` should also pass.

## 7. Start the dashboard

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_dashboard.ps1
# or:  .\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

Open http://localhost:8501.

- Maps work without internet. The base tiles (CartoDB and OpenStreetMap) need internet; the overlays and data do not.
- Section K, "Data quality and reproducibility", lists any missing file and can verify the checksums.

## 8. Legacy RF v0

See `RF_V0_RETIREMENT.md`. To run module G for traceability only:

```powershell
$env:CHENNAI_ALLOW_LEGACY_RF = "1"; .\run.ps1 -Only "G"; Remove-Item Env:CHENNAI_ALLOW_LEGACY_RF
```

Its outputs must never be shown or reported as a flood prediction.

## 9. Do not

- Commit, push or merge without the project owner's approval.
- Run `git clean` or `git reset`.
- Delete or overwrite SUS-1, S1WC-2, rainfall or DEP2 outputs.
- Modify `shive_upload_parts_20261126_093923`.
