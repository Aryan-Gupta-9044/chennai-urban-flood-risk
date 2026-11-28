# DEP-2 package: reference evidence, exposure and vulnerability (Chennai)

**Start with:** `outputs/dep2_reference_exposure_vulnerability_2026/DEP2_COMPLETION_REPORT.md`

## Package layout

These folders mirror the repository layout. Only new files are included.

| Path | Content |
|---|---|
| `src/dep2/` | modules: `acquire`, `cdmp`, `layers`, `reference`, `exposure`, `vulnerability`, `sus1_overlay`, `maps`, `mlcontract`, `common` |
| `scripts/dep2_run.py` | CLI: `acquire` / `evidence` / `reference` / `exposure` / `vulnerability` / `integrate` / `maps` / `contract` / `sus1overlay` / `manifest` / `all` |
| `tests/test_dep2.py` | 26 tests |
| `config/dep2.json` | the configuration for your machine (`aoi_mode: project`) |
| `config/dep2.cloud_run.json` | the exact configuration of the cloud run (substitute AOI, harness paths); kept as a record |
| `config/dep2_sources.json` | pinned URLs and SHA-256 for every source file |
| `config/evidence_register.json`, `config/event_chronology.json` | the authored evidence register and event chronology |
| `requirements-dep2.txt` | the one extra dependency (`pdfplumber`) |
| `data/external/dep2_sources/` | the redistributable originals only (open licences), plus `ACQUISITION_LOG.json`; everything else is fetched by `acquire` and hash-checked |
| `outputs/dep2_reference_exposure_vulnerability_2026/` | all results (A to G), the 12 maps, `SHA256SUMS.txt` and `run_manifest.json` |

## Rules

Nothing in this package overwrites existing project files. Copy only paths that do not already exist; the commands in `E_documentation/REPRODUCIBILITY_WINDOWS.md` do this.

Do not commit or push without the owner's decision.
