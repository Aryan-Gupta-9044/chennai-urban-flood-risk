# Testing and reproducibility record

## Latest complete local Windows suite

Command used:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q --ignore=shive_upload_parts_20261126_093923
```

Recorded result:
- 569 passed
- 1 skipped
- 0 failed
- 3,508 warnings
- Runtime approximately 197.87 seconds

The excluded path is a temporary duplicate package assembly containing a second copy of project modules. Its presence previously caused duplicate pytest module/package collection. It is local-only and excluded from Git. A clean checkout without that folder should use:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Dedicated integration tests

- FINAL-02: `pytest -q tests\test_final02.py` — 18 passed.
- DEP2: 26 tests passed in the recorded local verification.
- FINAL-01 reviewer environment: 526 passed, 1 skipped.
- S1WC-2 prior review: 25 tests passed.

These are historical recorded runs; rerun on the final release candidate and record the actual result before publication.

## Warning review

The full suite emitted 3,508 warnings. A known deprecation warning was reported at `scripts/s1_preprocess_2021.py:294` for GeoPandas/Shapely `unary_union`. Warnings are not test failures, but they should be reviewed and not hidden indiscriminately.

## ML-EXP-1.1 computational reproducibility

The original and rerun review used identical input hashes:
- Feature matrix: `67726685efff4d3760f451148312e615e4ace6a9d6d7f07254b757943e7bc8d3`
- Ward boundary gzip: `295a6788b2ef41493f54a13c0a98eb0957c36b5774ba617832cb14e1dd5eea15`

Matching output hashes:
- `pb_review_statistics.csv`: `2f7a1f85e07b37e2a66f82851be15788d30ef42b459ee4a041b9ffef398b9c64`
- `pb_review_null_draws.csv`: `1b2d70997f5184ef0df4821ae6b50ed816533c5257a6155d7bf627b5b5153a2d`

The comparison figure was pixel-identical. Runtime differed (approximately 910.8 s vs 1,172.5 s), which is not an analytical discrepancy. This verifies computational reproducibility for the compared inputs/outputs, not independent validity or predictive performance.

## Reproduction protocol

For every new run, record:
1. Git commit and branch.
2. Python version and dependency versions.
3. Exact command and configuration.
4. Input file paths, sizes and SHA-256 hashes.
5. Start/end time and exit code.
6. Warnings/errors.
7. Output manifest and checksums.
8. Comparison with accepted baseline.
9. Scientific interpretation and limitations.
10. Reviewer and acceptance status.

Never overwrite accepted outputs. Use a new versioned output directory.
