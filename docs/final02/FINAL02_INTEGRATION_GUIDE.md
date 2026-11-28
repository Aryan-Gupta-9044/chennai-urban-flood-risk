# FINAL-02 integration guide (Windows PowerShell)

- **Applies to:** the project root `C:\Users\aryan\Downloads\chennai-flood-risk-v2.3-dev\chennai-flood-risk` with FINAL-01 already applied (`ok=86`).
- **Do not reapply FINAL-01.**
- **No git commands are needed.** Do not commit, push, reset or clean.

## What the package contains

```
CHENNAI_FINAL02_OVERLAY_20261128.zip
  README_FINAL02.txt
  overlay/                 -> copy into the project root (new + changed files only)
  originals_FINAL01/       -> the FINAL-01 versions of every file the overlay replaces (for rollback)
```

**Replaced:** 14 existing files.

- the dashboard: `app.py`, `lib/maps.py`, `lib/registry.py`, `lib/ui.py`, and five `sections/*.py`
- `scripts/build_ward_analytics.py` and `src/analytics/ward_features.py` (POSIX paths in run records only)
- `paper/main.tex`, `paper/main.pdf` and `paper/README.md`

The FINAL-01 paper is also kept inside the overlay as `paper/main_v1_final01.tex` / `.pdf`.

**New:**

- two analysis scripts, one analysis module, one test file and an overlay verifier;
- two new output folders: `outputs/s1_temporal_context_v1` and `outputs/ml_review_v1_1`;
- `docs/final02/`;
- two paper figures.

**Never touched:** SUS-1, S1WC-1/2, S1PE, CHIRPS, both DEP2 runs, ML-EXP-1 and its rerun, `data/`, `FINAL01_PRE_INTEGRATION_BACKUP_20261128/`, `shive_upload_parts_20261126_093923/` and `outputs/tables/s1_inventory_cache/`.

## Steps

```powershell
cd C:\Users\aryan\Downloads\chennai-flood-risk-v2.3-dev
Get-FileHash .\CHENNAI_FINAL02_OVERLAY_20261128.zip -Algorithm SHA256      # compare with the delivery message
Expand-Archive .\CHENNAI_FINAL02_OVERLAY_20261128.zip -DestinationPath .\final02_staging

# 1. Optional own backup of the files that will be replaced (the package also carries them)
$dst = ".\FINAL02_PRE_INTEGRATION_BACKUP_20261128"
Get-ChildItem .\final02_staging\originals_FINAL01 -Recurse -File | ForEach-Object {
  $rel = $_.FullName.Substring((Resolve-Path .\final02_staging\originals_FINAL01).Path.Length + 1)
  $src = Join-Path .\chennai-flood-risk $rel
  if (Test-Path $src) { New-Item -ItemType Directory -Force -Path (Split-Path (Join-Path $dst $rel)) | Out-Null; Copy-Item $src (Join-Path $dst $rel) } }

# 2. Check that the files to be replaced are exactly the FINAL-01 versions (expect ok=14)
cd chennai-flood-risk
.\.venv\Scripts\python.exe ..\final02_staging\overlay\scripts\verify_overlay.py ..\final02_staging\originals_FINAL01\ORIGINALS_SHA256SUMS.txt
#    If this reports CHANGED for a file you edited after FINAL-01, stop and compare before copying.

# 3. Copy the overlay in
cd ..
robocopy .\final02_staging\overlay .\chennai-flood-risk /E /NFL /NDL

# 4. Verify (expect ok=52 changed=0 missing=0)
cd chennai-flood-risk
.\.venv\Scripts\python.exe scripts\verify_overlay.py docs\final02\PACKAGE_SHA256SUMS.txt

# 5. Tests (sandbox result: 565 passed, 4 skipped; plus 1 failure in the sandbox only, from the missing earthengine-api)
.\.venv\Scripts\python.exe -m pytest tests\test_final02.py tests\test_dashboard_unified.py tests\test_ml_exp1.py -q
.\.venv\Scripts\python.exe -m pytest -q

# 6. Dashboard
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_dashboard.ps1
```

No new Python packages are needed. `joblib` comes with scikit-learn.

## Optional: reproduce the new analyses

The outputs are already included.

```powershell
.\.venv\Scripts\python.exe scripts\build_s1_temporal_context.py --outdir outputs\s1_temporal_context_v1_rerun     # ~5 s
.\.venv\Scripts\python.exe scripts\build_ml_review.py --outdir outputs\ml_review_v1_1_rerun                       # ~15-25 min
```

- Both scripts refuse to write into accepted output folders.
- Both hash-check their inputs and exit with code 2 if any input changed during the run.
- `build_ml_review.py` uses fixed seeds, so the rerun should reproduce the table exactly.

## What to look at in the dashboard

| Where | What changed |
|---|---|
| Every map | Opens on Chennai with OpenStreetMap (no CARTO), a 10 km metric scale and a north arrow. It cannot be zoomed out beyond the region, and scroll-wheel zoom is off (use +/- or double-click). Ward outlines always show. A banner appears if tiles fail. |
| Sidebar | New overlay-opacity slider |
| J. ML and analytics | Cluster map with a categorical legend and a map-data check underneath. Run integrity reads "4 guarded inputs unchanged". The presence-background tab now ends with the ML-EXP-1.1 review (within-zone AUC, zone-stratified null, Holm/BH). |
| I. Sentinel-1 | Every drawn class is in the legend. New first tab: multi-date context (S1TC-1) |
| D. Susceptibility | Top-decile agreement legend uses the real codes |
| E, F, G | Quantile classes with ranges and units for skewed ward variables |
| K. Data quality | Verify buttons for the two new runs, hash-guard table and ward geometry check |

## Rollback

```powershell
robocopy ..\final02_staging\originals_FINAL01 . /E /NFL /NDL /XF ORIGINALS_SHA256SUMS.txt
```

The new files added by FINAL-02 can stay; nothing in FINAL-01 reads them. Alternatively, move them into a `_to_delete` folder.
