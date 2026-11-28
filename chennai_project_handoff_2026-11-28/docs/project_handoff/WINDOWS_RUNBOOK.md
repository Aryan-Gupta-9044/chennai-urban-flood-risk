# Windows PowerShell Runbook

Commands below reflect the last known Windows environment. Confirm the working directory and files before execution. Do not run expensive pipelines unless the relevant phase explicitly requires them.

## 1. Confirm repository and Git baseline

```powershell
Get-Location
git status --short --branch
git log -1 --format="%H%n%s"
git branch --show-current
```

Expected historical baseline:
- Branch: `milestone-2-3-4-checkpoint`
- Commit: `64c77c6676ec0270f1d8d81a7540ace1f82f0fad`

If the current checkout differs, stop and inspect before changing branches.

## 2. Activate/use the existing virtual environment

The known project commands used:

```powershell
& ".\.venv\Scripts\python.exe" --version
```

Do not recreate or overwrite `.venv` if it already works.

## 3. Run focused post-merge tests

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests\test_final02.py tests\test_dep2.py tests\test_dashboard_unified.py tests\test_ml_exp1.py
```

Historical result: 70 passed, 7 warnings in 15.36 seconds.

## 4. Run full test suite

Previously used:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q --ignore=shive_upload_parts_20261126_093923
```

Historical result: 569 passed, 1 skipped, 3508 warnings, 197.87 seconds.

The ignore path was needed because an uploaded archive/package directory caused duplicate module/package collection problems. Inspect current tests and tree before reusing the command.

## 5. Start dashboard

```powershell
& ".\.venv\Scripts\python.exe" -m streamlit run dashboard\app.py
```

Expected local URL historically: `http://localhost:8501`.

Open it in a browser, inspect the map, layers, controls, legends, and error messages. Stop with Ctrl+C. A successful startup alone is not a complete functional QA.

## 6. Inspect pipeline entry points

```powershell
Get-ChildItem scripts -File | Select-Object -ExpandProperty Name
```

Inspect each script's `--help` before running it:

```powershell
& ".\.venv\Scripts\python.exe" scripts\build_features.py --help
& ".\.venv\Scripts\python.exe" scripts\build_ml_review.py --help
& ".\.venv\Scripts\python.exe" scripts\build_s1_temporal_context.py --help
& ".\.venv\Scripts\python.exe" scripts\build_susceptibility_stack.py --help
& ".\.venv\Scripts\python.exe" scripts\build_ward_analytics.py --help
```

Only run a pipeline after confirming its inputs, output directory, runtime, and whether it overwrites accepted results.

## 7. Reproducibility and file integrity

Use SHA256 for input/output manifests. Example:

```powershell
Get-FileHash "path\to\file" -Algorithm SHA256
```

For directory-level verification, enumerate files deterministically, hash each, and compare against a manifest. Do not assume a previous `inputs_unchanged:true` flag covers every project input; earlier guard covered only a limited set.

## 8. Git safe workflow for future research

After confirming baseline and protecting untracked files, create a separate branch. Example branch name:

```powershell
git switch -c research/2026-11-28-scientific-audit
```

Only use this if the current branch is the verified baseline and no branch collision exists.

Stage explicit paths only:

```powershell
git add docs/project_handoff
git add PROJECT_STATUS_2026-11-28.md AGENT_MASTER_HANDOFF_2026-11-28.md
git status --short
git diff --cached --stat
git diff --cached --name-status
```

Review the complete staged file list before committing. Do not use `git add .`.

Then commit:

```powershell
git commit -m "docs: add complete project handoff and research status"
```

Push the new branch:

```powershell
git push -u origin research/2026-11-28-scientific-audit
```

Open a pull request and wait for explicit approval before merging.

## 9. Never run

Do not run:
- `git reset --hard`
- `git clean -fd`
- force push
- broad deletion/cleanup
- overwrite of accepted analytical outputs
- blanket `git add .`

Do not redistribute files marked `redistribute:false`.
