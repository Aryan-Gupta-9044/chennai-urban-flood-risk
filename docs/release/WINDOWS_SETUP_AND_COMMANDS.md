# Windows setup and command reference

Run commands from the repository root unless stated otherwise.

## Environment check

```powershell
.\.venv\Scripts\python.exe scripts\check_environment.py
```

## Test suite

For the current local working tree while the temporary package assembly exists:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q --ignore=shive_upload_parts_20261126_093923
```

For a clean checkout without that local-only folder:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Dashboard

```powershell
& ".\.venv\Scripts\python.exe" -m streamlit run dashboard\app.py
```

Stop with `Ctrl+C`.

## Inspect command-line options before processing

```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py --help
.\.venv\Scripts\python.exe scripts\dep2_run.py --help
.\.venv\Scripts\python.exe scripts\build_susceptibility_stack.py --help
.\.venv\Scripts\python.exe scripts\build_s1_temporal_context.py --help
.\.venv\Scripts\python.exe scripts\build_ml_review.py --help
```

## Git release safety

```powershell
git status --short --branch
git diff --stat
git diff --cached --stat
git diff --cached --name-status
```

Do not use `git add .` in this mixed working tree. Stage only reviewed paths. Before commit, inspect every staged file and confirm no local backups, caches, raw/restricted data, credentials or unintended generated outputs are included. Commit/push/merge only after explicit owner approval.
