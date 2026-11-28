# Repository Map and File Locations

This is a location guide based on the last known repository inventory. Confirm each path exists in the current checkout before editing.

## Root-level areas

| Path | Purpose / inspection |
|---|---|
| `README.md` | Main project overview and quick start |
| `config/` | Pipeline configurations and source manifests |
| `data/` | Raw/processed source data; protect and inspect licenses |
| `src/` | Core implementation |
| `scripts/` | Pipeline and report-building entry points |
| `tests/` | Pytest suite |
| `dashboard/` | Streamlit application |
| `outputs/` | Generated products, reports, tables and figures |
| `docs/release/` | Release and reproducibility documentation |
| `docs/final/` | Earlier final integration evidence/decision records |
| `docs/final02/` | FINAL-02 integration documentation |
| `paper/` | LaTeX manuscript, PDF, bibliography and figures |

## Known scripts

- `scripts/build_features.py`
- `scripts/build_ml_review.py`
- `scripts/build_s1_temporal_context.py`
- `scripts/build_susceptibility_stack.py`
- `scripts/build_ward_analytics.py`
- `scripts/dep2_run.py` (verify exact current location/name)

## Known paper files

- `paper/main.tex`
- `paper/main.pdf`
- `paper/main_v1_final01.tex`
- `paper/main_v1_final01.pdf`
- `paper/references.bib`
- `paper/README.md`
- `paper/IEEEtran.cls`
- `paper/IEEEtran.bst`
- `paper/figures/`

## Known release documentation

- `docs/release/COMPLETE_PIPELINE_GUIDE.md`
- `docs/release/SCIENTIFIC_LIMITATIONS.md`
- `docs/release/TESTING_AND_REPRODUCIBILITY.md`
- `docs/final02/FINAL02_INTEGRATION_GUIDE.md`
- `docs/final02/MAP_DEFECT_DIAGNOSIS.md`

## Known outputs

- `outputs/reports/status.json`
- `outputs/reports/data_quality_report.json`
- `outputs/tables/feature_table_sample.csv`
- `outputs/ml_review_v1_1/`
- `outputs/ml_review_v1_1_rerun/` (local rerun; preserve; previously ignored by Git)
- SUS-1 and S1WC-2 outputs (inspect actual subdirectories)
- DEP2 outputs (inspect actual subdirectories)

## Source manifests and evidence files to locate

- `config/dep2_sources.json`
- `dep2_integration_copied_files.json`
- `config/evidence_register.json`
- `config/event_chronology.json`
- `sus1_overlay_NOT_RUN.json` (historical marker; verify current status)

## Local-only items reported at last status check

- `config/dep2.cloud_run.json`
- `config/dep2.local.json`
- `dashboard/legacy/`
- `scripts/_legacy/`

These were untracked and intentionally preserved. `dep2.cloud_run.json` contained `/home/claude/...` paths and harness-only configuration; `dep2.local.json` was a local Windows configuration. Do not add these to Git without sanitisation and explicit review.

## Protected archives and backups

- `shive_upload_parts_20261126_093923/`
- `outputs/tables/s1_inventory_cache/`
- `FINAL01_PRE_INTEGRATION_BACKUP_20261128/`
- `FINAL02_PRE_INTEGRATION_BACKUP_20261128_180647/`
- `FINAL03_PRE_DOCS_BACKUP_20261128/`

Do not delete, move, overwrite or commit these wholesale.
