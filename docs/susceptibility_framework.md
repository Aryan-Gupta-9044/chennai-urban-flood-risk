# SUS-1: exploratory relative flood-susceptibility framework

**Status: EXPLORATORY. Uncalibrated. Not independently validated.**
SUS-1 is the project's **exploratory baseline** (accepted with qualifications after the methodology review, `docs/susceptibility_review_report.md`).
It is not a flood prediction model, not a flood extent, not a flood hazard map, and not a flood-risk assessment (exposure and vulnerability are not integrated).
No flood labels of any kind are used, no weight or threshold is fitted to anything, and no accuracy or calibrated flood probability has been established.

## Run

```powershell
python scripts/build_susceptibility_stack.py                 # full run -> outputs/susceptibility_v1  (~1.5 min)
python scripts/build_susceptibility_stack.py --stack-only    # aligned feature stack + diagnostics only
python scripts/susceptibility_review.py                      # methodology review (read-only on SUS-1) -> outputs/susceptibility_review_v1
python -m pytest tests/test_susceptibility.py tests/test_susceptibility_review.py -v
```
Exit codes: `0` ok, `2` stopped before writing (misaligned or missing input, output exists, protected location), `3` an input changed during the run.
The script never overwrites (the output directory must not exist or be empty), writes only inside `outputs/susceptibility_*`, never touches `status.json`, S1WC-1,
CHIRPS, persistence or reference outputs, and makes no network / Earth Engine requests. It does not import S1WC-2.

## Evidence classes

| Class | Contents |
|---|---|
| Observed input data | Copernicus GLO-30 DSM (raw elevation); CHIRPS native 0.05° event total; Sentinel-1 backscatter (only through S1WC-1 summaries) |
| Derived indicators (existing pipeline) | slope, conditioned DEM, D8 flow accumulation, drainage network, TWI |
| Derived indicators (new here) | distance to drainage, HAND-proxy, fill depth |
| Assumptions | indicator set and direction, normalisation method, equal default weights, domain mask, hotspot rule, the 300 m planning-block size |
| Exploratory outputs | index, quintile classes, hotspots, block ranking, sensitivity statistics |

Every indicator is a **derived terrain/hydrology proxy computed from one DSM**. None is an observed flood measurement.

## Grid
The master grid is the project grid: EPSG:32644, 30 m, 1416 × 726, origin (406020, 1463310). The AOI is the **provisional OSM boundary** (~435 km², not the official GCC boundary).
Every input raster must match the grid exactly (shape, CRS, transform, one band) or the run stops before writing. Nothing is silently resampled.
The single exception is native CHIRPS (10 × 7 cells at 0.05°), which is replicated by nearest neighbour (no interpolation) as a context layer only.

## Indicators (all in the index with equal weight 1/7 by default)

| Indicator | Direction (more susceptible) | Transform / normalisation | Note |
|---|---|---|---|
| elevation_m | lower | rank percentile | raw GLO-30 (a DSM, not a bare-earth DTM); relative to this AOI only |
| slope_deg | lower | rank percentile | central difference at 30 m on the raw DEM |
| twi | higher | rank percentile | relative and unvalidated; slope-clamped where slope < 0.1° (flagged in `twi_slope_clamp_flag.tif`); strongly functionally related to slope and flow accumulation (see "Weights") |
| flow_accumulation | higher | log10, then robust min–max (p2–p98) | D8 on the conditioned DEM |
| dist_to_drainage_m | lower | robust min–max (p2–p98) | Euclidean distance to DEM-derived drainage cells; truncated at the AOI edge |
| hand_proxy_m | lower | robust min–max (p2–p98) | conditioned DEM minus conditioned DEM at the **Euclidean-nearest** drainage cell, clipped at 0. **It is a proxy, not flow-path HAND** |
| fill_depth_m | higher | robust min–max (p2–p98) | conditioned minus raw DEM (max 1 m by construction); zero for ~93% of scored cells and largely pit-scale, so it may reflect DSM artefacts rather than ponding. It must not be read as a depth |

Scores run from 0 to 1, with 1 = more susceptible **relative to the other scored cells of this AOI**. The reference population for normalisation is the scored domain,
so scores are not transferable to another area or date.

**Context layers (not in the index, never labels):**
- CHIRPS event total. About 29 native CHIRPS cells intersect the AOI, so it carries no usable sub-5 km spatial information. The per-date antecedent rainfall means are recorded in the manifest only.
- S1WC-1 dark-recurrence layers (`n_dark_dates`, `n_valid_dates`, `persistent_dark_mask`, `transient_candidate_date_count`).
  They are **provisional** Sentinel-1 evidence. Date-level radiometric offsets make candidate counts non-comparable across dates, and about half of S1WC-1 candidates sit on the DEM flattened-water signature.
  Transient dark candidates are not confirmed floodwater, and persistent dark pixels are not confirmed permanent water.

## Domain, excluded cells and NoData
- Outside the AOI → class 255.
- **Provisional DEM flattened-water signature** → class 2, **excluded and not assessed**. It is DEM == 0 or a ≥ 30-cell 4-connected constant-value plateau.
  It is a DEM-artefact flag and not a water mask. The plateau rule is re-implemented in `susceptibility.py`, independently of the S1WC-2 package.
- Any active indicator missing → class 3, not scored. NoData becomes NaN, never 0 and never "non-flood".
- Otherwise → class 1, scored.

**Excluded cells are "not assessed".** They must never be read as zero susceptibility, low or no flood risk, non-flooded or safe. Indeed the excluded cells are low (median elevation 0.5 m against 10.3 m for scored cells), flat and high-TWI.
In the index and score rasters they are NoData (−9999), not 0, and they carry no hotspot or block label.
**`hotspot_label.tif` is ambiguous:** its value 0 means "not a hotspot", "excluded" and "outside the AOI" alike. Always consult `domain_class.tif` (1 scored, 2 excluded, 3 missing indicator, 255 outside AOI) to tell them apart. Never read 0 as "not flood-prone".
In the quintile raster, 0 = not scored and 255 = outside the AOI.
The flattened-water rule is provisional: it may also remove genuinely flat land, it cannot flag water bodies whose DSM values are not constant, and the 3,620 slope-clamped scored cells remain in the domain.

## Index
`index = Σ wᵢ·scoreᵢ / Σ wᵢ` (weighted arithmetic mean; weights configurable in `config/susceptibility.json`; zero weight deactivates an indicator).
The raster `susceptibility_relative_class_quintile.tif` holds rank-based quintiles. These are relative classes and are **not** risk levels or probabilities.

### Weights: equal weights are a modelling assumption
The default is **equal weights (1/7 each), chosen so that nothing is tuned**. This is a modelling assumption. It is not empirically optimal, not statistically validated and not objectively established.
The methodology review found **substantial redundancy** among the indicators (`outputs/susceptibility_review_v1/tables/t1_*`):
- **TWI is strongly functionally related to slope and flow accumulation** (rank R² ≈ 0.93). That is expected from TWI = ln(acc·res / tan slope).
- Variance-inflation factors are 15.7 (TWI), 8.9 (slope) and 7.8 (flow accumulation); the other four indicators are 1.2–1.6.
- The seven indicators carry about **four independent information dimensions** (effective number 4.05 of 7).
- **Nominal weights are not actual contributions.** With equal weights the three wetness-family indicators hold 43% of the nominal weight but drive about 52% of the index variation (TWI alone about 21%, the largest single share). Fill depth, at the same nominal weight, drives about 6%.

### Alternative index (not adopted): six indicators without TWI
The review identified a six-indicator alternative with TWI removed and equal weights of 1/6 (scheme `C_reduced_no_twi`) as a **defensible alternative candidate**.
Against the baseline it has a Spearman rank agreement of 0.982 (≈ 98%) and a top-decile overlap (Jaccard) of 0.890, and no indicator dominates its variation (shares about 8% for fill depth to 22% for elevation).
**It has not replaced the adopted seven-indicator SUS-1 baseline.** Weights, indicator selection and index calculations are unchanged, and any adoption (a "SUS-1.1" or "SUS-2") needs an explicit owner decision and a separate versioned run.
The grouped weightings tested were not defensible improvements (3 groups promotes fill depth to a third of the weight; 2 groups raises TWI's variation share to about 25%). See the review report. Alternative rasters and tables are in `outputs/susceptibility_review_v1`.

## Sensitivity
All runs use the same scored cells.
- Named scenarios: terrain-heavy, hydrology-heavy, drop-one-indicator (×7), and two alternative normalisations (all-rank, all-robust-min–max).
- 500 seeded random-weight runs (Dirichlet, concentration 5 per indicator, seed in config).

Reported against the base index: Spearman rank correlation and top-decile Jaccard (`tables/sensitivity_*.csv`), per-cell top-decile frequency, and per-cell index range.
The index itself is stable (Spearman ≥ 0.92 against the base in every scenario). **The ranking of individual SUS-1 hotspot polygons by mean index is not** (below).
Stability across weight scenarios is robustness to construction choices, never accuracy.

## Hotspot polygons (exploratory footprints)
Top decile (≥ p90) of the scored domain → 8-neighbour connected components of ≥ 25 cells → polygons (`vectors/susceptibility_hotspots_exploratory.gpkg`, plus a WGS84 GeoJSON).
Each carries area, mean/max index, mean raw and normalised indicator values, robustness fields, and `ctx_*` descriptive context columns.
**The `ctx_*` columns are NOT validation** and must not be read as agreement or accuracy.
The hotspot id is the raster-scan label and is not a rank. The polygons are the **footprint** of the most susceptible terrain. They are **not** the headline ranking and not flood extents.
The top decile is highly fragmented (8,048 components, median 1 cell; only about 57% of its cells lie in ≥ 25-cell components), and the larger hotspots are ragged drainage-corridor networks.

## Primary planning ranking: mean index within fixed 300 m blocks
**The primary ranking for spatial planning is the mean SUS-1 index within fixed 300 m planning blocks** (10 × 10 cells, 9 ha; a block is kept if at least 50% of its cells are scored).
Evidence (review, 511 scenarios): block ranking retains about **85%** of its top 10 across the scenarios (0.853), and behaves similarly at 150 m (0.895) and 600 m (0.809). The block grid needs no threshold, minimum size or merging.
Outputs: `outputs/susceptibility_review_v1/rasters/block_mean_index.tif`, `block_label.tif`, `vectors/review_top200_blocks.gpkg`, `tables/t2_units_block_geometry_all_rankings.csv`.
**The 300 m block size is an analytical/planning assumption. It is not a universally validated or optimal spatial unit.** No ward boundary exists in the repository, so ward-level aggregation is not possible.
Blocks with ≥ 50% scored cells may still contain excluded (not assessed) cells.

**Not the headline method: the original hotspot-polygon `rank_by_mean_index`.** It is retained in `hotspot_ranking.csv` and the review tables for comparison only. It favours small, high-scoring fragments (the top-10 mean area is about 10 ha) and is unstable: only 57% of its top 10 survive the 511 scenarios,
and hotspot #1 (a 56-cell fragment) ranges from rank 1 to 64 because its mean sits within one scenario-spread of the next hotspots. Do not present it as the ranking.

**Secondary measure: area-weighted excess susceptibility** (Σ(index − p90) × area, per hotspot). It is very stable (0.99 top-10 retention) but **that stability is substantially driven by hotspot area**: its rank correlation with an area-only ranking is about 0.93, and 9 of its top 10 are also the 10 largest.
It must not be presented as an independent measure of susceptibility intensity. It describes the extent of large connected low-lying corridors.

## Channel circularity (applies to every hotspot map, block ranking and hotspot reading)
About **98.3% of scored drainage-network cells fall in the top susceptibility decile**, and about 31% of top-decile cells have a HAND-proxy of 0. The drainage network is derived from the same DEM and flow accumulation that feed three of the indicators.
The index therefore **partly restates drainage/channel patterns derived from the DEM**. High-ranked channels or channel-adjacent blocks do **not** independently demonstrate flood occurrence, and they are **not** model validation.
Read hotspots and blocks as "low-lying, convergent terrain along DEM-derived drainage", not as inundation. A future version should treat channel cells and the surrounding floodplain separately.

## Limitations
1. **No independent flood reference exists**, so the index cannot be calibrated, validated or scored for accuracy. No calibrated flood probability or validated accuracy has been established. This is **not a validated flood-risk model**, and any statement that it "predicts flooding" is unsupported.
2. **Susceptibility only.** Exposure and vulnerability are not integrated into SUS-1. There is no land-cover, ward, population or shelter data in the repository, so ward-level aggregation is not possible.
3. **Indicators are correlated and share one source.** All seven come from one DSM and its derivatives. About four independent information dimensions are present, and nominal weights do not equal actual contributions (see "Weights").
4. **GLO-30 is a DSM, not a bare-earth DTM.** Buildings and vegetation affect elevation and slope. Copernicus GLO-30 flattens water bodies. Negative elevations occur (min −16.8 m) and are used as given.
5. **No drainage infrastructure.** Real urban drainage, storm drains, pumping, tanks, tidal/coastal influence and channel capacity are not represented. The drainage network is a DEM-derived proxy, which introduces circularity (above).
6. **HAND-proxy is a Euclidean-nearest-drainage proxy, not flow-path HAND**, and 9.1% of AOI cells (8.4% of scored cells) were clipped from a negative value to 0. Keeping the signed values changes the result little (Spearman 0.9998, top-decile Jaccard 0.974).
7. **TWI is relative and unvalidated** and is slope-clamped for 3,620 scored cells (0.8%).
8. **Fill depth is largely zero** (~93% of scored cells) and mostly pit-scale (85% of its patches are ≤ 4 cells), so it may reflect DSM artefacts. It must not be read as ponding depth.
9. **Rainfall is not spatially resolved at this scale** (see above).
10. **Edge effects.** Distance to drainage is truncated at the provisional AOI boundary.
11. **Hotspot polygon ranks by mean index are fragile**; use the block ranking (above) and read hotspots with their area and robustness fields.
12. **The AOI and the flattened-water exclusion remain provisional.** The AOI is the OSM boundary, not the official GCC boundary. Excluded cells are not assessed.
13. **The 300 m block size and the normalisation methods** (rank vs min–max) are untested against any reference.

## Interpretation
Safe: "Under these terrain/hydrology assumptions, these areas are relatively more susceptible than other parts of the provisional AOI, and these blocks/areas are or are not robust to weight choices."
Not supportable: probabilities, return periods, damage or risk, "flood-prone" or "safe" labels, validation, accuracy, or agreement with observed floods.
**What would make it defensible:** an independent, verified flood reference (the R3–R5 gate), then ward/land-cover exposure layers. Only after that can weights be evaluated, and never on S1WC-1 outputs.
