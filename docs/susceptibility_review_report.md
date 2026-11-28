# SUS-1 methodology review (SUS-1-REVIEW-1)

**Status: EXPERIMENTAL REVIEW of an exploratory, uncalibrated, unvalidated index.** Nothing here is a validation, a prediction-accuracy statement, or a flood-risk assessment.
The accepted SUS-1 baseline was not modified (all its files were hash-checked before and after). The alternatives live in `outputs/susceptibility_review_v1`. No flood labels, S1WC-1 outputs or S1WC-2 products were used as validation.
Agreement between alternatives only measures **robustness to construction choices**, not correctness against reality.

Reproduce: `python scripts/susceptibility_review.py` (about 4 min; needs `outputs/susceptibility_v1`), then `python -m pytest tests/test_susceptibility_review.py -v`.

## Acceptance recommendation: ACCEPT WITH QUALIFICATIONS
SUS-1 is internally consistent and honest about its limits. All 17 audit checks pass (Task 3). No defect invalidates it as an exploratory product, and the main alternatives change the top decile only moderately (Jaccard 0.89–0.90).
It should be accepted as the baseline **on these conditions**:
1. Treat the equal-weight 7-indicator index as one construction choice, not a finding. The review found measurable double-counting of the wetness family (Task 1). `C_reduced_no_twi` is a defensible sensitivity candidate (Spearman 0.982, top-decile Jaccard 0.890 against the baseline). It was **not adopted** and the baseline is unchanged; any future adoption (for example a SUS-1.1) is a separate project decision.
2. Do not present the SUS-1 hotspot ranking by mean index as a ranking (Task 2). Use the block-based ranking, with corridor "excess" as context.
3. State that drainage-channel cells score near-maximal by construction (98.3% of scored drainage cells are in the top decile). The hotspots are best read as "low-lying drainage-corridor terrain", not as inundation (Task 4).
4. Excluded cells are "not assessed", never "not flooded".
5. Keep every output labelled EXPLORATORY. The unresolved limitations in section 6 stay attached to any use of the product.

## Task 1: indicator redundancy
Scores are Spearman-correlated over the 471,472 scored cells (`t1_*` tables).
- **TWI is almost a function of slope and flow accumulation.** Rank-regressing TWI on the two explains **R² = 0.93**. That is expected from the formula TWI = ln(acc·res / tan slope).
- **Variance-inflation factors:** TWI 15.7, slope 8.9, flow accumulation 7.8; the other four are 1.2–1.6. The effective number of independent indicators is **4.05 of 7**.
- **Double-counting:** with equal weights the three wetness-family indicators hold 43% of the nominal weight but drive **52%** of the index variation (TWI alone 21.3%, the largest single share, despite 1/7 weight).

| Scheme | Weights | Spearman vs A | Top-decile Jaccard vs A | Index mean / sd | Share of A's hotspot cells still hotspot |
|---|---|---|---|---|---|
| A baseline (7 equal) | 1/7 each | 1 | 1 | 0.450 / 0.164 | 100% |
| B grouped, 3 groups (wetness: slope, TWI, flow acc; low-ground: elevation, HAND, distance; depression: fill) | fill 1/3, others 1/9 | 0.996 | 0.785 | 0.359 / 0.148 (skew 0.97) | 82% |
| B2 grouped, 2 groups (fill joins low-ground) | wetness 1/6 each, low-ground 1/8 each | 0.996 | 0.900 | 0.444 / 0.170 | 89% |
| **C reduced: TWI dropped** | 1/6 each of 6 | 0.982 | 0.890 | 0.442 / 0.153 | 95% |

**Grouping logic.** TWI is a derived product of two indicators that are already in the set. Slope and flow accumulation are kept because they have direct physical meaning and no clamp artefact.
Elevation, HAND-proxy and distance-to-drainage all describe "how low or close to a channel"; fill depth describes local sinks.
- **B** over-corrects. It promotes fill depth, which is zero for 93% of cells and is mostly pit-scale, to a third of the index (24% of the variation). That is not defensible.
- **B2** does not reduce the double-counting. It gives the wetness family half the weight, so TWI's variation share rises to 25%. It is retained as a documented negative result.
- **C** gives a less uneven spread of variation shares than A (8.0–21.9%, max/min ratio 2.8 against 3.5 for A) and removes the TWI dependence, at the cost of a moderate change to the top decile (Jaccard 0.89). TWI is 93% reconstructible from slope and flow accumulation. It is also consistent with the SUS-1 drop-TWI scenario (Jaccard 0.89).

**Finding: C (6 equal-weight indicators, no TWI) is a defensible sensitivity candidate. It has not been adopted.** A remains the accepted baseline; any adoption needs a separate project decision and a separate versioned run. There is no independent reference, so the review does not show that C is more accurate than A. Spatial patterns: For C, 91% of cells shift by ≤10 percentile points and all by ≤20 (p1–p99: −14.5 to +12.8). For B2 and B, 99% shift by ≤10. See `review_schemes_maps.png` and the `percentile_difference_*` and `top_decile_agreement_*` rasters.
The remaining arbitrary choices (equal weights within groups, rank vs min–max normalisation) are not resolved by this review.

## Task 2: hotspot ranking
**Why hotspot #1 ranged from rank 1 to 64.** It is a 56-cell (5 ha) fragment with mean 0.854. The gap to the next-ranked hotspot (0.036) is about the same size as the scenario-to-scenario SD of its own mean (0.034).
It is a channel-like segment (scores 0.97–0.98 on elevation, TWI, flow accumulation, distance and HAND), but only 0.63 on slope and 0.46 on fill depth. Under `random_007` (slope 0.32, distance 0.23, flow accumulation 0.05) it falls to rank 64. Its median rank is 1.
It is a ranking-noise problem of tiny, near-tied units, not a data fault.

| Ranking / geometry | Hotspot units | Top-10 retention across 511 scenarios | Median rank range of top 10 (relative to n) |
|---|---|---|---|
| Mean index, SUS-1 baseline (≥25 cells) | 204 | 0.57 | 91.5 (45%) |
| Mean index, min area 50 / 100 / 200 / 400 cells | 96 / 47 / 26 / 12 | 0.65 / 0.71 / 0.85 / 0.98 | 55 / 26.5 / 15 / 9 |
| Excess susceptibility (Σ(index − p90)·area), baseline geometry | 204 | 0.99 | 3.5 (1.7%) |
| Excess susceptibility, merged (closing ×1) | 224 | 0.94 | 2 (0.9%) |
| Mean index, 150 / 300 / 600 m planning blocks | 18,881 / 4,739 / 1,192 | 0.90 / 0.85 / 0.81 | 10 / 15.5 / 11.5 (≤1%) |

**Findings.**
- **Mean-index ranking** favours small fragments. The top-10 mean area is 10 ha against 111 ha for the largest, and only 57% of the top 10 survive scenario changes. Raising the minimum area stabilises it, but only at 12 hotspots covering 49% of the baseline hotspot cells (28% of top-decile cells) at min 400 cells.
- **Excess (area-weighted) ranking** is very stable (0.99). But its Spearman with a pure area ranking is 0.93, and 9 of its top 10 are also the 10 largest. Its stability mostly reflects the stability of area. It identifies large connected low-lying corridors. It does not measure intensity.
- **Fragmentation is severe.** The top decile is 8,048 8-connected components with a median of 1 cell. Only 57% of its cells sit in ≥25-cell components. The largest hotspots are ragged networks (compactness 0.002–0.012), consistent with drainage corridors.
- **Merging by closing is a poor fix.** One closing pass adds 27,596 cells that are not in the top decile (+59%). Two passes add 83,650 and percolate into a single 53,190-cell component. Hotspot membership then no longer means "top decile".
- **Planning blocks** (fixed 300 m cells, ≥50% scored) need no threshold, minimum size or merging. They give comparable 9-ha units, keep 85% top-10 retention and a rank range ≤1% of n, and behave the same at 150 and 600 m. Their rank-range statistic is flattered by the large n (4,739), so top-10 retention is the fairer figure.

**Recommendation.** Use the **300 m block mean index** as the primary ranking for spatial planning, because it is stable, threshold-free and at a planning grain, and show the SUS-1 hotspot polygons as the footprint.
Add **excess susceptibility** as a secondary "corridor extent" measure. Retain the original mean-index ranking only for comparison (`rank_mean_index` is kept in every table).
The block size is itself an assumption. No ward boundary exists in the repository, and ward aggregation (the natural planning unit) remains impossible.
Stability across weights is not accuracy.

## Task 3: exclusion and coverage audit (`t3_audit_checks.csv`; all 17 PASS)
- **AOI and grid.** The AOI mask recomputed from the polygon equals `domain_class != 255` exactly (483,727 cells). All SUS-1 rasters and the raw DEM sit exactly on the master grid.
- **Domain classes.** Classes 1/2/3 cover each AOI cell once: 471,472 scored, 12,255 excluded, 0 with a missing indicator. This matches the manifest.
- **Exclusion reproduced independently.** The 12,255 excluded cells are exactly the independently recomputed DEM signature (DEM = 0: 5,097; plateau-only: 7,158).
- **Scored cells.** All 7 raw indicators and all 7 normalised scores are finite, and scores are in [0,1]. The index is finite and in [0,1].
- **Non-scored cells.** Excluded and outside cells carry index and score NoData (−9999), never 0. They carry no hotspot label. In the quintile raster they are 0 (excluded) and 255 (outside), distinct from class 1.
- **Reproducibility.** The index recomputed from the stored scores equals the SUS-1 raster (max diff 5e-8). All 511 scenarios reproduce the SUS-1 sensitivity table (max diff 1.3e-8).
- **Finding to fix in a future version.** `hotspot_label.tif` uses 0 for "not a hotspot", "excluded" and "outside the AOI" alike. This is a representation ambiguity, not a computation error. `domain_class.tif` resolves it. **Never read 0 as "not flood-prone".**
- **Exclusion adjacency.** 12.1% of scored cells within 3 cells (90 m) of an exclusion are in the top decile, against 9.9% elsewhere. The exclusions sit inside or next to susceptible terrain.

## Task 4: scientific interpretation
All seven indicators are **derived terrain/hydrology proxies from one DSM**. None is an observed flood measurement.
- **HAND-proxy** is not hydrological HAND. It uses the Euclidean-nearest drainage cell, not the flow path, so it can mix catchments. 8.4% of scored cells (9.1% of the AOI) have a negative value, meaning they are lower than their nearest drainage cell, and SUS-1 clips them to 0. Their median is −0.72 m and p05 −3.6 m.
  Treating them as the highest-susceptibility cells (HAND = 0) is a choice. Keeping the signed values changes the index trivially (Spearman 0.9998, top-decile Jaccard 0.974), and dropping the indicator changes it modestly (0.980 / 0.867). The clipping is therefore not driving the results. Flow-path HAND would be the proper indicator.
- **Fill depth** = conditioned − raw DEM, capped at 1 m by the filling rule. It is zero for 93% of cells. Among the 6.9% with fill > 0, the median is 0.21 m. Only 0.14% reach the cap. 85% of its 9,830 patches are ≤4 cells and the median patch is 1 cell, which is pit scale and plausibly DSM noise or micro-sinks. Only 22% of filled cells lie in patches ≥25 cells.
  It is a weak, noisy depression indicator. It must not be read as ponding depth or as a flood-depth measurement. It rightly carries low index influence (about 6%).
- **TWI and flow accumulation** are formula-dependent (R² 0.93). 3,620 scored cells (0.8%) are slope-clamped at 0.1°. Their TWI is a clamp artefact, not terrain information, and 54% of them fall in the top decile. They are flagged in `twi_slope_clamp_flag.tif`.
- **Channel circularity.** 98.3% of scored drainage cells are in the top decile, and 31% of top-decile cells have HAND = 0. The network is derived from the same DEM and flow accumulation that feed three of the indicators.
  The index therefore partly re-states "where the DEM-derived channels are" and "low ground along them". A future version should treat channel cells and the surrounding floodplain separately.
- **Flattened-water exclusion** is provisional and DEM-artefact based. The excluded cells are low (median 0.5 m against 10.3 m), flat (slope 0°) and high-TWI. They are the kind of cells that would plausibly rank high if scored. They are not assessed, and they are **not** "safe". The rule can also remove genuinely flat land (e.g. paddy, paved or built plateaus; no land cover exists to check), and it cannot flag real water bodies with non-constant DSM values.
  The 3,620 clamped cells and any undetected flat water remain in the scored domain.

## 5. Planning construction and sensitivity candidate
- **Index:** the accepted baseline A (7 equal-weight indicators) is unchanged. C (6 indicators without TWI) is a sensitivity candidate only and is **not adopted**.
- **Ranking:** 300 m block mean index (primary), with corridor excess susceptibility as secondary context.
- **To keep:** the SUS-1 baseline outputs unchanged, until the project decides.

## 6. Unresolved scientific limitations
1. No independent flood reference, so nothing is calibrated or validated, and equal weights remain an assumption.
2. Susceptibility only. Exposure and vulnerability are absent, and there is no land-cover, ward or population data.
3. All indicators come from one DSM (not bare earth). Buildings, vegetation and DSM noise propagate.
4. HAND is a Euclidean proxy. Real urban drainage, pumping, tidal and coastal processes and channel capacity are not represented.
5. Channel circularity, plus the floodplain-versus-channel distinction (above).
6. The flattened-water exclusion is provisional and may remove susceptible flat land. Excluded means "not assessed".
7. The block size and the normalisation methods (rank vs min–max) are untested against any reference.
8. Rainfall is not spatially resolved at this scale (about 5 km CHIRPS).
9. The AOI is the provisional OSM boundary, not the official GCC boundary.
10. Stability across scenarios is a statement about robustness to construction choices, never about accuracy.
