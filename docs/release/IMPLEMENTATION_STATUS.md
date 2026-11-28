# Implementation status and acceptance evidence

**Snapshot date:** 28 November 2026  
**Status labels:** implementation/test status is distinct from scientific acceptance.

| Component | Implementation evidence | Current interpretation / open qualification |
|---|---|---|
| S1WC-2 | Eight 2021 dates processed; prior review recorded 25 tests passing and zero VV/VH mismatch across 16 checks | Candidate water-related radar signal only |
| SUS-1 | 30 m EPSG:32644 grid; 483,727 AOI cells, 471,472 scored, 12,255 provisional exclusions | Relative susceptibility; provisional AOI and terrain proxy caveats |
| DEP2 | 146 package files integrated; local config run exit 0; 26 dedicated tests passed | Reference evidence classes vary; acquired/copied manifest reconciliation remains |
| FINAL-01 | ZIP SHA `8C44F6D7D6A8D05EB1BAA9A9BE2927E63F92CF98DB557E3FE16F77A8B0A18763`; Windows verification `ok=86 changed=0 missing=0`; reviewer tests 526 passed, 1 skipped | Integration evidence retained under `docs/final/` |
| FINAL-02 | ZIP SHA `d6b04917ebdc0eddd5a54933bcee27d5dc8d1b04f5eed40faadc11493d02b203`; 52 manifest files verified; 18 dedicated tests passed | Integration evidence retained under `docs/final02/` |
| Full Windows suite | 569 passed, 1 skipped, 3,508 warnings, excluding temporary SHIVE package assembly | Software test evidence, not scientific validation |
| ML-EXP-1.1 rerun | Matching input hashes; exact matching statistical and null-draw CSV SHA-256; pixel-identical comparison figure | Computational reproducibility for these artefacts only |
| Dashboard | User previously reported dashboard view functioning; FINAL-02 screenshots retained | Recheck live app before making a new release-time visual claim |
| IEEE draft | `paper/main.tex`, `paper/main.pdf`, figures and bibliography present | Working draft; author placeholders and reference checks remain |

## Open research and release actions

1. Agent 1 verifies every bibliography item against original sources.
2. Confirm evidence-class wording against `docs/final/EVIDENCE_DECISION_LOG.md`.
3. Resolve official GCC boundary availability; if changed, rerun affected spatial workflows in a new output version.
4. Reconcile DEP2 acquired-source and copied-file manifests.
5. Review DEP2 depth-class extraction/reconciliation issues.
6. Continue independent reference acquisition and resolve E39–E51 evidence gaps.
7. Decide whether any event reference qualifies for quantitative validation.
8. Only then decide whether an integrated risk method or prediction study is justified.
9. Complete supervisor approval, author/affiliation details, acknowledgement and venue compliance before submission.
