# FINAL-02 baseline and review-archive register

- **Date:** 28 Nov 2026
- **Workspace:** the patch was built in a separate copy of the project. That copy is FINAL-01 merged PART1–3 plus the Windows `outputs/ml_exploratory_v1_rerun` from the review ZIP.
- **Original archives:** opened read-only, extracted only into staging directories, never copied over the project.

## 1. Windows repository state (as supplied by the owner)

| Item | Value | Verified how |
|---|---|---|
| HEAD | `815dffc37e36ccf70ed9fe4fff36f4e04ba1bdfd` (27 Nov 2026 19:55 +0530, "feat: add susceptibility review and update project documentation") | `git_head.txt` supplied by the owner |
| Branch | `milestone-2-3-4-checkpoint` per the prompt | **Not verified:** no `git branch --show-current` output was supplied |
| Tracked, modified | `dashboard/app.py`, `outputs/reports/status.json`, `scripts/run_pipeline.py`, `src/flood_detection/ref_integration.py`, `tests/test_ref_integration.py` | `git_status.txt`, `git_diff_stat.txt` (200 insertions, 136 deletions) |
| Untracked | 32 entries, including `FINAL01_PRE_INTEGRATION_BACKUP_20261128/`, `shive_upload_parts_20261126_093923/`, `outputs/tables/s1_inventory_cache/`, DEP2 and FINAL-01 files | `git_status.txt` |
| FINAL-01 overlay on Windows | `ok=86 changed=0 missing=0` (owner report) | Consistent: every dashboard, code and paper file in the review ZIPs is byte-identical to FINAL-01 |

FINAL-02 is an overlay of new and changed files only:

- It does not touch the untracked backup, upload or cache folders.
- It never runs git.
- It does not reapply FINAL-01.

## 2. Review archives

| Archive | Bytes | SHA-256 | Files | Purpose and version | Compared with the current project |
|---|---|---|---|---|---|
| `01_CORE_CODE_REVIEW.zip` | 2,758,650 | `7135181ef1803b96936635b5df9a3865277b3a7065fa0732c10c371e78f5d7cd` | 301 | Code-review snapshot of the Windows tree after FINAL-01 (config, dashboard, src, scripts, tests, docs) | 223 files identical; **0 differ**; 77 extra files are all `__pycache__/*.pyc` (Python 3.11 bytecode, not reviewed) |
| `02_RESULTS_EVIDENCE_REVIEW.zip` | 46,039,845 | `950705641dc6537862d6484b472921e19f2af64dd951d33e507f6d6516dab277` | 239 | Results snapshot: susceptibility, DEP2 local run, ML-EXP-1, reports, tables | 213 identical, 0 differ, 23 new = `outputs/ml_exploratory_v1_rerun` (Windows rerun of ML-EXP-1; see §3) |
| `03_PAPER_REVIEW.zip` | 3,371,318 | `5cda93b96f2f67e3626b138e8889632b0c33fd10a9791e13ea2fe6cf28a25e1c` | 26 | FINAL-01 paper and `docs/final` | 26 identical, 0 differ |

The archives use Windows `\` separators; `unzip` converted them.

Earlier archives from this project (PART1–3, the dashboard review ZIP, and the DEP-2 and DEP-1 packages) were inventoried in FINAL-01 (`docs/final/MISSING_FILES_REPORT.md`) and were not re-reviewed.

### Not available for inspection

- **The six dashboard screenshots** the owner supplied earlier are NOT AVAILABLE FOR INSPECTION in this environment. They are not in any of the three archives. The defects were taken from the prompt's description (§7) and reproduced or diagnosed against the code; see `MAP_DEFECT_DIAGNOSIS.md`.
- **The DEP2 integration ZIP** (`F17EA480…EED8`) and **the DEP2.1 ZIP** (`D219A5A5…130A`) were not supplied in this turn, so their identity was not re-checked. The DEP2 integration ZIP was produced and hashed in an earlier turn.

## 3. Windows rerun of ML-EXP-1

`outputs/ml_exploratory_v1_rerun/ml_exp1_summary.json` matches the original on every scientific value:

- all 16 presence-background rows, the clusters and the PCA are identical;
- PC1–3 differs only at the 16th digit (0.6620301196422531 vs …533).

It took 659.5 s on Windows against 453.2 s in the sandbox.

**Defect found:** the Windows run recorded paths with `\` separators. FINAL-02 records POSIX paths in `build_ward_analytics.py` and `ward_features.py`. This is metadata only; the results are unchanged.

## 4. Protected outputs

- Per-file hashes:
  - `susceptibility_percentile.tif`: `dfdc91bb…727625`, matching the prompt.
  - `domain_class.tif`: `80efb84fdb79a17b0e9cd709b3262226b389ebb1e0e88beb38a29b1ac539c22d`.
- **The prompt's domain_class hash is a transcription error.** It omits the characters `0e` (`…ebb1e88beb…`). The file is unchanged: the value above is the one recorded by DEP2 and ML-EXP-1.
- Tree digests of every protected folder were recorded before and after FINAL-02 (`PROTECTED_TREE_HASHES_BEFORE.json`, `..._AFTER.json`). The folders covered are SUS-1, SUS-1 review, S1WC-1/2, S1PE, CHIRPS 2021, both DEP2 runs, ML-EXP-1 and its rerun, `s1_inventory_cache`, `data/` and the preserved paper.

## 5. Source-manifest audit (prompt §9.2–9.3)

`SOURCE_MANIFEST_AUDIT.csv` re-hashes all 62 records in `data/external/dep2_sources/ACQUISITION_LOG.json`. This is the pinned-commit acquisition manifest, with URL, repository, commit, path, bytes and SHA-256 for each record.

- **62 of 62 are present, with matching bytes and SHA-256.**
- That includes the two CDMP PDFs, which are marked `redistribute: false`. They stay in `data/` and are **excluded from every FINAL-02 package**.
- All 146 entries of `dep2_integration_copied_files.json` exist in the project.
- 22 of the 62 source files are listed by path in that integration manifest. The other 40 are under the `data/external/dep2_sources` folder, which the integration copied as a whole.

**There is no integration gap.** The prompt's own copy of the manifest was not attached, so the audit uses the in-repository log that the prompt describes. Its values were not retyped.

## 6. Prompt truncation

Both master prompts received in this turn were truncated:

- "FINAL CORE PROJECT IMPROVEMENT PATCH" stops at line 793, in §9.
- "FINAL MAJOR IMPROVEMENT PATCH" stops at line 798, in §10.

Requirements after those points were not visible. Work followed every visible section.
