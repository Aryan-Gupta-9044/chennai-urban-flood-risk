# MASTER AGENT HANDOFF — CHENNAI URBAN FLOOD-RISK PROJECT

You are the Pro agent and execution lead for the project **Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data**, focused on Chennai, Tamil Nadu, India.

## Verified baseline
- Repository: https://github.com/Aryan-Gupta-9044/chennai-urban-flood-risk
- PR #1 merged: https://github.com/Aryan-Gupta-9044/chennai-urban-flood-risk/pull/1
- Merge commit: `64c77c6676ec0270f1d8d81a7540ace1f82f0fad`
- Branch: `milestone-2-3-4-checkpoint`
- 70 post-merge focused tests passed; earlier full suite 569 passed, 1 skipped.
- Dashboard started and visually checked.
- Required release artifacts 15/15 present.

## Mission
Complete the remaining research and publication-readiness work:
1. Agent 1 independent review of paper, bibliography, DOI records, claims and novelty.
2. Reconcile source acquisition, hashes, processing, integration and use.
3. Scientifically assess DEP2–SUS-1 compatibility and decide whether overlay is justified.
4. Identify truly independent flood observations and improve valid comparisons.
5. Audit ML statistics, spatial/temporal leakage, null models and multiple testing.
6. Prepare supervisor review package and IEEE venue comparison.
7. Revise a new paper version only after evidence review.
8. Produce reproducibility manifests, tests and final handoff.

## Agent split
**Pro agent:** implementation, pipeline inspection, experiment execution, reproducibility, integration, documentation and coordination.

**Agent 1:** independent literature, source, evidence, methodology, statistics, novelty and manuscript review. Agent 1 must be free to disagree and must provide written evidence.

## First action
Inspect the actual repository and current Git state. Confirm the baseline and protect all untracked files, backups, datasets and accepted outputs. Create a separate development branch only after checking for conflicts. Do not edit the milestone release branch.

## Protected items
Preserve:
- `config/dep2.cloud_run.json`
- `config/dep2.local.json`
- `dashboard/legacy/`
- `scripts/_legacy/`
- `shive_upload_parts_20261126_093923/`
- `outputs/tables/s1_inventory_cache/`
- `FINAL01_PRE_INTEGRATION_BACKUP_20261128/`
- `FINAL02_PRE_INTEGRATION_BACKUP_20261128_180647/`
- `FINAL03_PRE_DOCS_BACKUP_20261128/`
- all existing DEP2, SUS-1, S1WC-2, ML and FINAL-02 outputs.

No `git reset --hard`, `git clean`, force push, broad deletion or `git add .`. Never overwrite accepted outputs. New experiments go into new versioned directories.

## Scientific baselines and caveats
Read `docs/project_handoff/PROJECT_CONTEXT.md` and `docs/project_handoff/SCIENTIFIC_CAVEATS_AND_EVIDENCE.md` first. They contain the known metrics and interpretation limits.

Critical facts:
- SUS-1 AOI is provisional; GLO-30 is DSM; HAND is Euclidean-nearest-drainage proxy; wetness indicators are correlated.
- Sentinel-1 class 1 is a candidate water-related signal, not confirmed floodwater.
- DEP2 reference evidence includes PRESENCE_ONLY and QUALITATIVE_ONLY classifications; acquisition/copy manifests need reconciliation.
- ML clustering represents indicator-profile groups, not flood-severity classes.
- ML results are exploratory; no robust supervised flood prediction has been established.
- No validated flood prediction accuracy or calibrated flood probabilities have been established.
- Eight S1 dates do not support strong rainfall-response conclusions.
- Correlated enrichment is not independent validation.

## Required sequence
1. Baseline inventory and protection.
2. Paper/reference and source/evidence audit; Agent 1 review.
3. DEP2–SUS-1 scientific compatibility assessment.
4. Independent validation gap analysis and comparison protocol.
5. ML/statistical audit.
6. Supervisor package and IEEE venue assessment.
7. Evidence-led paper v3.
8. Final reproducibility, tests and handoff.

## Deliverables
Create `docs/research/` reports and registers for:
- baseline integrity;
- paper/reference audit;
- claim/evidence register;
- source reconciliation;
- evidence status register;
- DEP2–SUS-1 scientific audit and decision;
- validation gap, protocol, inventory and results;
- ML statistical audit and decision register;
- supervisor package and questions;
- IEEE venue comparison and requirements;
- final research handoff.

Create paper v3 only after relevant gates pass. Preserve FINAL-01 and FINAL-02.

## Reporting
At each milestone report completed, attempted, blocked, Agent 1 review pending, user/supervisor decisions needed, files changed, commands actually run, tests actually executed and next actions.

Do not invent sources, DOIs, results, tests, venue deadlines or validation metrics. If evidence is unavailable, report the gap. Do not submit papers or contact the supervisor without user approval.

## Definition of success
The project is independently reviewable, evidence-traceable, reproducible, scientifically honest and appropriately prepared for an IEEE opportunity. A documented inability to validate with current data is preferable to fabricated validation.

Start by returning a baseline inventory and execution plan. Do not immediately rewrite the paper, add another ML model or generate a combined risk score.
