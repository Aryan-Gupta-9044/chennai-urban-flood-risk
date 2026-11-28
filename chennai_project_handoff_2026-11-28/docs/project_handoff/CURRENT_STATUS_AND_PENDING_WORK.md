# Current Status and Pending Work — 28 November 2026

## 1. Verified software release

| Item | Last verified status |
|---|---|
| PR #1 | Merged |
| PR URL | https://github.com/Aryan-Gupta-9044/chennai-urban-flood-risk/pull/1 |
| Merge commit | `64c77c6676ec0270f1d8d81a7540ace1f82f0fad` |
| Base branch | `milestone-2-3-4-checkpoint` |
| Release branch | `release/2026-11-28-final-documentation` |
| PR changed files | 128 |
| Post-merge focused tests | 70 passed, 7 warnings |
| Earlier full Windows suite | 569 passed, 1 skipped, 3508 warnings |
| Dashboard smoke test | Started; user confirmed working |
| Required artifacts | 15/15 present |
| Tracked Git diff | Clean |
| Staged Git diff | Clean |

The four untracked local items reported at the last check were preserved:
- `config/dep2.cloud_run.json`
- `config/dep2.local.json`
- `dashboard/legacy/`
- `scripts/_legacy/`

They are not release deliverables. Do not delete or commit blindly.

## 2. Completed engineering work

- DEP2 integration and associated documentation/tests.
- Unified dashboard and related dashboard fixes.
- FINAL-02 overlay installation with 52 manifest-listed files verified.
- Paper draft v2 / FINAL-02 integration.
- Documentation and release packaging.
- Focused post-merge test suite.
- Dashboard startup check.
- GitHub PR #1 merge and local branch synchronization.

Earlier full suite: `569 passed, 1 skipped`; post-merge focused suite: `70 passed`. These are software tests, not scientific validation.

## 3. Reproducibility rerun completed

ML-EXP-1.1 full rerun was completed into `outputs/ml_review_v1_1_rerun/` and must be preserved.

- Runtime: 1172.5 seconds.
- `inputs unchanged: True`.
- Feature input hash: `67726685efff4d3760f451148312e615e4ace6a9d6d7f07254b757943e7bc8d3`.
- Ward boundary gzip hash: `295a6788b2ef41493f54a13c0a98eb0957c36b5774ba617832cb14e1dd5eea15`.
- Statistics CSV SHA256: `2f7a1f85e07b37e2a66f82851be15788d30ef42b459ee4a041b9ffef398b9c64`.
- Null draws CSV SHA256: `1b2d70997f5184ef0df4821ae6b50ed816533c5257a6155d7bf627b5b5153a2d`.
- Figure pixels were identical between original and rerun.
- Summary JSON differed semantically only in runtime.

This demonstrates computational reproducibility for the checked inputs and outputs, not scientific validity or independent flood validation.

## 4. High-priority pending tasks

### P1 — Agent 1 independent paper/reference review
- Verify every bibliography entry, DOI, title, authors, year and venue.
- Verify `gcc2026cdmp` and `iwmi2015chennai` specifically.
- Check whether each citation supports the exact claim.
- Independently assess novelty, methods, results, limitations and wording.
- Produce a claim-to-evidence register and unresolved-source list.

### P1 — Source and evidence reconciliation
- Reconcile acquisition manifests against copied-file manifests.
- Distinguish discovered, acquired, hash-verified, processed, integrated, analysed and independently validating sources.
- Verify licenses, redistribution restrictions, temporal coverage, CRS and spatial coverage.
- Preserve original evidence statuses unless new evidence justifies a documented change.

### P1 — DEP2–SUS-1 scientific integration assessment
- Earlier `sus1_overlay_NOT_RUN.json` recorded that the overlay had not run; inspect current files to confirm present state.
- Check CRS, grid alignment, AOI, masks, temporal compatibility, spatial support and correlated inputs.
- Investigate double counting and indicator dependence.
- Decide whether a defensible multi-layer screening framework is preferable to a combined numerical risk score.
- If justified, run only into a new versioned output directory and label it exploratory.

### P1 — Independent validation gap analysis
- Inventory authoritative independent event observations and flood extents.
- Check time, geography, resolution, methodology and licensing.
- Do not treat reports, OSM, candidate SAR signals or susceptibility maps as ground truth without justification.
- Use metrics only where labels and sampling design support them.
- Document shared inputs and correlated errors.

### P1 — ML/statistical audit
- Recheck pooled vs within-zone AUC.
- Recheck zone-stratified nulls and permutation design.
- Clarify multiple-testing family and post-hoc choices.
- Address limited RF permutation resolution.
- Preserve clustering as indicator-profile grouping.
- Do not promote exploratory findings into prediction claims.

### P2 — Supervisor and venue preparation
- Prepare a short review package and precise questions for supervisor.
- Research suitable IEEE venues using official pages.
- Mark future deadlines unannounced if not published.
- Do not submit or pay fees without user approval.

### P2 — Paper v3
- Revise only after evidence and Agent 1 review.
- Preserve FINAL-01 and FINAL-02 files.
- Compile and check citations, figures, tables, page limits and template.
- Do not claim submission readiness while critical evidence gaps remain.

## 5. Later work

- Supervisor feedback.
- Final venue choice.
- Author/affiliation details after approval.
- Venue-specific template conversion.
- Final manuscript revision and submission preparation.

## 6. Explicit scientific status

The current ML results are exploratory. The project has not established validated flood prediction accuracy or calibrated flood probabilities. The SUS-1 product is a susceptibility screening layer; Sentinel-1 class 1 is a candidate water-related signal; DEP2 evidence classifications include presence-only and qualitative-only cases.
