# Project Status — 28 November 2026

**Project:** Integrated Geospatial Framework for Urban Flood Risk Mapping and Prediction Using Multi-Source Data (Chennai)

## Verified software baseline
- GitHub repository: https://github.com/Aryan-Gupta-9044/chennai-urban-flood-risk
- PR #1 merged: https://github.com/Aryan-Gupta-9044/chennai-urban-flood-risk/pull/1
- Merge commit: `64c77c6676ec0270f1d8d81a7540ace1f82f0fad`
- Branch: `milestone-2-3-4-checkpoint`
- 70 post-merge focused tests passed; earlier full suite 569 passed, 1 skipped.
- Dashboard startup and visual smoke check completed.
- Required release artifacts: 15/15 present.

## Completed
- SUS-1, S1WC-2, DEP2, ML-EXP-1/1.1 and FINAL-02 software integration/documentation at the known release baseline.
- ML-EXP-1.1 reproducibility rerun completed; checked CSV hashes and figure pixels matched.
- Unified dashboard, tests, release documentation and paper draft integrated.

## Pending — high priority
1. Agent 1 independent paper/reference audit.
2. Source acquisition/integration manifest reconciliation.
3. DEP2–SUS-1 scientific integration decision.
4. Independent validation inventory and feasible comparison protocol.
5. ML/statistical interpretation audit.
6. Supervisor review package and IEEE venue comparison.
7. Evidence-led paper v3 and final review.

## Scientific status
Current ML findings are exploratory. No validated flood prediction accuracy or calibrated flood probabilities have been established. Sentinel-1 class 1 is a candidate water-related signal, not confirmed floodwater. SUS-1 is a susceptibility screening product. DEP2 evidence statuses include presence-only and qualitative-only classifications.

## Git safety
Preserve the merged release. Perform future work on a separate branch. Do not reset, clean, force-push, overwrite outputs, or use `git add .`. Preserve local untracked configs, legacy folders, backups and analytical outputs.
