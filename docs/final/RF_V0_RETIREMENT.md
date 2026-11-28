# Retirement of "Flood susceptibility (RF v0)" (module G)

**Decision (FINAL-01, 28 Nov 2026, implementation side):** Legacy RF v0 is **RETIRED**. It must not be shown, exported or described as a flood prediction, a susceptibility map or a validated model.

This decision does not change any evidence status. Agent 1 and the project owner can confirm it or reverse it; see `AGENT1_REVIEW_QUESTIONS.md`, question Q1.

## Why it is retired

1. **Proxy labels.** `train_random_forest.py` takes its labels from `data/external/flood_labels/*.tif` or, failing that, from `flood_extent_*_utm44n_30m.tif`, which are Sentinel-1 water-candidate rasters ("SAR PROXY").
   - The project accepts S1 candidates only as **E4 candidates, not flood truth**: S1WC-2 classes, the reference checker, and the CDMP 2021 against bright-VV result with ratios 0.37 to 1.09.
   - A model trained on S1 candidates learns the candidate algorithm, not flooding.
2. **Circularity.** The same S1 bands, or bands derived from them, can enter the feature stack. Any accuracy reported against proxy labels is circular.
3. **No negatives.** No source provides verified "not flooded" cells. Pixels absent from a report or a candidate map are unlabelled, not negative.
4. **Random pixel splits.** Validation on 30 m pixels that are spatially autocorrelated overstates skill. ML-EXP-1 shows that under zone-blocked validation, even ward-level reported labels are not learnable beyond the ward-area control.
5. **Missing artefacts.** `flood_susceptibility_rf_v0.tif` and `outputs/models/` are absent from all four input packages. No RF v0 result exists to display.

## What was changed

| File | Change |
|---|---|
| `scripts/train_random_forest.py` | **None.** sha256 `92072df9…e7668` is identical to PART1 and the review ZIP. Kept for traceability. |
| `scripts/run_pipeline.py` | Module G is skipped unless the environment variable `CHENNAI_ALLOW_LEGACY_RF=1` is set, and a warning is logged when it is skipped. New sha256 `be0b50a7…0bb00`. |
| `scripts/_legacy/run_pipeline_v0_before_rf_gate.py` | Verbatim copy of the previous `run_pipeline.py`, sha256 `9011da8c…842e`. |
| `dashboard/app.py` | No RF v0 layer. Section J shows RF v0 only as a RETIRED entry with these reasons. The original dashboard is kept as `dashboard/legacy/app_v0_initial.py`. |
| Tests | `test_pipeline_rf_gate` and `test_no_rf_v0_layer` enforce both changes. |

## What replaces it

- **ML-EXP-1** (`outputs/ml_exploratory_v1`): exploratory ward structure plus a presence-background test. It is EXPLORATORY and NOT VALIDATED.
- **The supervised-model data contract** (`outputs/dep2_local_run_01/G_ml_dashboard/ml_data_contract.json`): states what labels would be required. At least one of the following:
  - an E1/E2 extent dated within a few days of an S1 pass;
  - dated reports;
  - credible negatives;
  - an independent second event for testing.
