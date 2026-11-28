# Questions for Agent 1 (scientific review), FINAL-01

Each question needs a decision. The implementation side has not acted on any of them beyond what is recorded in `EVIDENCE_DECISION_LOG.md`.

| # | Question | Default if no answer |
|---|---|---|
| Q1 | Confirm the retirement of RF v0 (`RF_V0_RETIREMENT.md`). Should module G be deleted from the pipeline eventually, or stay gated? | Stays gated, and the trainer is kept unchanged |
| Q2 | Is presence-background AUC with zone-blocked CV, a 500 m buffer and label-permutation nulls an acceptable *exploratory* test for E3 PRESENCE_ONLY ward labels? Should a spatially restricted null replace the simple permutation null? | Reported as EXPLORATORY and NOT VALIDATED |
| Q3 | Should the R2 notes for REF-2021-CDMP and REF-2015-CDMP record the reporting-opportunity (ward-area) effect found in ML-EXP-1? | No status change |
| Q4 | Clarify the checker's "0 day(s)" temporal evidence for year-level windows (see log C.1). Is a wording change in `ref_integration` wanted? It would be a code change and needs owner approval. | Unchanged |
| Q5 | The paper candidate (`paper/main.pdf`): check every bibliography entry against its source, especially `gcc2026cdmp`, `iwmi2015chennai`, `zhao2024review` and `chini2019coherence`. Check that the evidence-class wording matches the register. | Not submittable until checked |
| Q6 | Is the two-cluster ward typology (silhouette 0.30) worth a paper figure, or should it stay in the dashboard only? | In the paper as Fig. 2, labelled exploratory |
| Q7 | The five wards that are "high on reported, exposure and vulnerability" (DEP2 D) are shown as an exploratory profile. Is that acceptable wording for the dashboard and the paper? | Kept as an exploratory profile |
| Q8 | Which acquisition would most change the evidence position: the GCC 2021 inundation map (EV-2021-02, georeferenced), UNOSAT 2015 (EV-2015-04), or dated 2021 reports? | Data contract lists all three |
| Q9 | The study area is still the provisional OSM AOI (~435 km²). Should the analysis switch to the TNGIS ward union (432 km²) as the study area, in a new versioned run? | No change |
