# Evidence decision log (FINAL-01)

**Role separation.** This log is written by the implementation side (SHIVE workstream, executed by the agent). It records how existing evidence statuses were *used*. It does **not** upgrade any status. Every item marked "Agent 1" needs a scientific-review decision.

## A. Statuses preserved exactly

These come from `outputs/dep2_local_run_01/A_evidence_reference/checker_runs/*/R2_readiness.json` and were re-read on 28 Nov 2026.

| Reference | Intake | Alignment | Primary class | Used in FINAL-01 as |
|---|---|---|---|---|
| REF-2021-CDMP | WARNING | WARNING | PRESENCE_ONLY | Ward presence (≥1 listed location). Wards without a listing are UNLABELLED. Null comparisons only. |
| REF-2015-CDMP | WARNING | FAIL | QUALITATIVE_ONLY | 2015 presence for ML-EXP-1 presence-background analysis and cross-event transfer. Never used to validate 2021 or S1 2021. |
| REF-2015-OSMIN-DEC2 | WARNING | FAIL | QUALITATIVE_ONLY | 2015 cross-source consistency against CDMP 2015 only. |

All other register items keep their DEP2 classes (`evidence_register.csv`). EV-2021-04 (S1PE) is E4. The CHIRPS, IMD and news context is E5. Items that were not acquired stay not acquired.

## B. Decisions made in FINAL-01 (implementation-level, reversible)

| ID | Decision | Reason | Effect on claims |
|---|---|---|---|
| D-F01 | RF v0 retired; module G gated (`RF_V0_RETIREMENT.md`) | Proxy labels, circular, no negatives | Removes a non-claimable layer |
| D-F02 | E3 ward presences used as *presence-background* labels in ML-EXP-1, never as negatives | The PRESENCE_ONLY class allows presence-only analysis | Only PB-AUC against permutation nulls is reported. No accuracy, precision, recall, F1 or IoU. |
| D-F03 | 2015 labels used in ML-EXP-1 only as a separate event and for transfer tests | QUALITATIVE_ONLY with respect to S1 2021; 2015 must not validate 2021 | Transfer AUC is reported as exploratory, not as validation |
| D-F04 | The dashboard shows ward report status in three classes: "reported", "not listed (unlabelled)" and "not assessed" | Absence of a report is never negative | No "flood-free" wording anywhere (enforced by a test) |
| D-F05 | Reports, coarse rainfall and the partial-coverage WorldPop are excluded from the ML-EXP-1 model features | Leakage, coarseness and coverage | Documented in `ward_features.FEATURE_SPEC` and tested |
| D-F06 | SUS-1 candidate C (no-TWI) kept as a sensitivity variant only | ρ 0.982 and Jaccard 0.890 against A, so there is no basis to switch | SUS-1 baseline is unchanged |
| D-F07 | Limitations and provenance CSVs in the dashboard are read from the DEP2 cloud documentation package | The local run wrote no `E_documentation` files; the code is the same | Section K labels the source |

## C. Observations for Agent 1 (not acted on)

1. **Year-level windows and "0 days".** The REF-2021-CDMP R1 evidence reads "closest S1 date 2021-09-05 is 0 day(s) from the reference observation". The observation range was deliberately set to the calendar year 2021 because the source gives only the year. Every S1 date therefore falls inside the window. The "0 days" is a property of the window, **not** a date match. The status (WARNING / PRESENCE_ONLY) is unaffected. Agent 1 may want the checker wording or the window convention clarified.
2. **Reporting opportunity.** In ML-EXP-1, ward area is the only feature set with a nominally significant PB-AUC (2021: 0.557, p = 0.04), and it also transfers best between events. This supports treating CDMP counts as reporting-biased. Agent 1 should decide whether the R2 notes should carry this caveat.
3. **2015 cross-source agreement.** CDMP 2015 and osm-in (2 Dec) agree 2.5 times above the street null at 50 m. This is the strongest positive result for any E3 source. It does not change their QUALITATIVE_ONLY status with respect to S1 2021.
4. **Bright-VV (E4).** There is no association with CDMP 2021 at 0–100 m. The only small excess is at 250 m on 4 and 28 Nov. Recommendation: keep S1PE as a diagnostic only.

## D. Not done, because they would require a status change

- No S1 date was relabelled as "flood" and no extent was created.
- No 2015 → 2021 validation was performed.
- No ward was labelled negative.
- No vulnerability composite is presented as a complete social-vulnerability index. It is labelled PARTIAL.
