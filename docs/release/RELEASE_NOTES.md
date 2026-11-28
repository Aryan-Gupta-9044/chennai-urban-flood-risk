# Release notes — documentation and integration baseline

**Prepared:** 28 November 2026  
**Branch:** `release/2026-11-28-final-documentation` (local release-preparation branch; verify before publication)

## Included workstreams

- FINAL-01 and FINAL-02 dashboard/integration updates.
- DEP2 reference, exposure and vulnerability integration.
- SUS-1 susceptibility and sensitivity review.
- S1WC-2 candidate-water workflow and S1TC temporal context.
- ML-EXP-1 exploratory ward analytics and ML-EXP-1.1 statistical review.
- IEEE-style paper draft and figure set.
- New release documentation covering architecture, pipeline, dashboard, provenance, limitations, testing, paper preparation and open actions.

## Recorded integration evidence

- FINAL-01 package SHA-256: `8C44F6D7D6A8D05EB1BAA9A9BE2927E63F92CF98DB557E3FE16F77A8B0A18763`
- FINAL-02 package SHA-256: `d6b04917ebdc0eddd5a54933bcee27d5dc8d1b04f5eed40faadc11493d02b203`
- FINAL-02: 52 manifest-listed files verified after copy; dedicated tests 18 passed.
- Full local Windows suite: 569 passed, 1 skipped, 3,508 warnings, with temporary duplicate package assembly excluded.
- ML-EXP-1.1 reproducibility rerun: matching inputs, matching key statistical outputs and pixel-identical comparison figure.

## Exclusions

Local backups, temporary SHIVE package assemblies, local inventory caches, ML rerun output, raw/large geospatial source files, restricted CDMP PDFs, secrets and unreviewed archives must not be added to the public repository.

## Important status note

These notes document the work and evidence available on 28 November 2026. They do not assert that a Git commit, push, PR merge or publication submission has occurred.
