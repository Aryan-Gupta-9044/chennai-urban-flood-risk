# Handoff verification and missing-files report (FINAL-01)

## Input packages (verified 28 Nov 2026)

| Package | Files | Size | SHA-256 |
|---|---|---|---|
| CHENNAI_DASHBOARD_REVIEW_20261128_110818.zip | 169 | 43,587,344 B (as expected) | `5b6e593a26b5b7f280d56606da9adb0cb9c48ecc42f8d9db3c77874854076fa8` |
| CHENNAI_SHIVE_PROJECT_PART1_CODE_20261128.zip | 329 | — | `cc06b457e254c3127f4c45646fda44353633e777e63bcc6aaf2773e090355b75` |
| CHENNAI_SHIVE_PROJECT_PART2_DATA_20261128.zip | 864 | — | `9fca4e3df00db414a90c67cbaaa28cf3796de53a54f22022512610d657409e75` |
| CHENNAI_SHIVE_PROJECT_PART3_RESULTS_20261128.zip | 591 | — | `c6afce8bf862eed8deedc81fd2dca6293721198ac37a2ad91a169e3dc7bd5351` |

- The per-file inventory lists 1,953 entries with path, bytes and SHA-256; see `HANDOFF_FILE_INVENTORY.csv`.
- PART1, PART2 and PART3 merge without conflict: 157 paths are shared and all are byte-identical.
- **The review ZIP was not used to replace any authoritative file.** Its copies of the shared files were compared and are identical.

## Integrity findings

| Finding | Assessment |
|---|---|
| PART1 `SHA256SUMS.txt`: 2 mismatches (`src/.../ref_integration.py`, `tests/test_ref_integration.py`) | Known local change REF-AREA-CRS-QA-01, made after the manifest was written. Owner to confirm. |
| No `.git` directory in any package | Branch and HEAD **cannot be verified** from the packages. Run `git status` and `git log -1` on Windows. |
| `earthengine-api` not installed in the sandbox | Causes 1 environment-only test failure (`test_import_src`). Not a code fault. |

## Missing or empty (expected by older code or docs)

| Path | State | Impact |
|---|---|---|
| `data/external/wards/`, `boundary/`, `landcover/`, `dem/` | empty | None for FINAL-01. The wards come from the DEP2 GPKG; the DEM-derived SUS-1 rasters are present in processed form. |
| `outputs/models/` | empty | No RF v0 model exists (see `RF_V0_RETIREMENT.md`) |
| `flood_susceptibility_rf_v0.tif` | absent | The legacy dashboard layer cannot be shown, and is retired anyway |
| `outputs/tables/dataset_inventory.csv` | absent | The legacy dashboard table is replaced by section K and this inventory |
| `outputs/dep2_local_run_01/E_documentation/` | empty | Limitations and provenance are read from `outputs/dep2_reference_exposure_vulnerability_2026/E_documentation/` (same code) |
| Mapped flood extent (E1) for any S1 date | not obtainable | Blocks validation, accuracy metrics and supervised prediction |

The dashboard registry (93 paths) reports **0 missing files** after this overlay. Section K re-checks this every time it runs.

## Prompt note

The FINAL-01 master execution prompt was received **truncated at section 6.1** ("Similarity between wards. P…"). Requirements after that point were not visible. Ward similarity (kNN, clusters) was implemented from the sections that were visible. If sections 6.1 onward contained further requirements, send the rest of the prompt.
