# Hydrological terrain analysis - methodology and results (V2.3)

**All products are TERRAIN-DERIVED and UNVERIFIED.** The drainage network is not stormwater infrastructure; no hydrological validation exists or is claimed.

## Input
`dem_elevation_utm44n_30m.tif`, EPSG:32644, 30 m, 726x1416 cells, 483727 valid cells, elevation -16.82 to 53.76 m (mean 10.05, median 10.097).
SHA-256 before/after the run: identical (DEM unchanged) (`1a92502ec57e616c...`).
The study-area boundary is the provisional OpenStreetMap polygon; NoData cells outside it are never used or crossed.

## Method
1. **Validation**: projected CRS = EPSG:32644, square north-up pixels, no rotation, at least one valid cell, NoData mask.
2. **Negative-elevation diagnostics**: 154 cells (0.032%) in 40 clusters; 2.6% lie within 300 m of the NoData edge; 98.7% lie in closed depressions. Per-cluster table: `hydrology_negative_clusters.csv`. Negative cells are NOT automatically treated as errors: they could be genuine below-datum low ground, vertical-datum effects or source artefacts, and this analysis cannot tell which.
3. **Conditioning (conservative priority-flood, Barnes et al. 2014 with epsilon 1e-06 m/cell)**: outlets are valid cells on the raster edge or touching NoData. The full fill gives spill-level depth D. Closed depressions are 8-connected groups with D > 0.01 m. A depression whose maximum fill depth is <= 1.0 m is filled (micro-relief/artefact); a deeper one is **kept unfilled** as an internal sink. Result: 12466 depressions, 8889 filled, 3577 kept. Cells raised by more than 0.01 m: 31682 (6.550% of valid cells, 28.514 km2); max raise 1.000 m; volume added 8173147 m3; no cell is lowered. The conditioned DEM is stored as float64 because the epsilon gradients (1e-6 m) are lost in float32. Sensitivity to the depth limit: `hydrology_depression_sensitivity.csv`.
4. **D8 flow direction**: steepest strictly-descending neighbour (diagonals scaled by sqrt 2, ties broken in fixed E,SE,S,SW,W,NW,N,NE order, so results are deterministic). NoData is never a target. Codes: E1 SE2 S4 SW8 W16 NW32 N64 NE128, 0 outlet/sink, 255 NoData.
5. **Flow accumulation**: topological (Kahn) algorithm in cells including the cell itself; a cycle raises an error. Conservation check: accumulation summed over terminal cells = number of valid cells -> **True**. Terminal cells: 19392 (1628 outlets on the NoData edge, 17764 internal sinks).
6. **Drainage extraction**: contributing area >= 0.1008 km2 = 112 cells -> 5394 channel cells; vector: 4990 segments, 176.9 km. Threshold sensitivity: `hydrology_drainage_threshold_sensitivity.csv`.
7. **TWI**: generated (slope clamp 0.1 deg affects 2.61% of cells). Formula ln(a/tan beta), a = contributing area / cell size (D8), slope from `slope_deg_utm44n_30m.tif`, slopes clamped at 0.1 deg, generated only if the clamp affects <= 30.0% of cells.

## Largest negative clusters
- cluster 24: 30 cells, min -11.49 m, 3093 m from NoData edge, closed depression: True, kept unfilled: True
- cluster 3: 20 cells, min -16.82 m, 1515 m from NoData edge, closed depression: True, kept unfilled: True
- cluster 33: 13 cells, min -0.90 m, 1742 m from NoData edge, closed depression: True, kept unfilled: True
- cluster 12: 7 cells, min -4.89 m, 1615 m from NoData edge, closed depression: True, kept unfilled: True
- cluster 18: 6 cells, min -4.55 m, 2460 m from NoData edge, closed depression: True, kept unfilled: True

## Assumptions and limitations
- The study-area edge acts as an outlet; contributing area from outside the boundary is ignored, so accumulation near the edge is underestimated (edge effect).
- A 30 m DEM (Copernicus GLO-30 is a surface model including buildings/vegetation) does not resolve culverts, drains, bridges or underpasses; urban flow paths can differ strongly from terrain-derived ones. No stormwater network was used.
- Kept (deep) depressions stop all flow, which breaks connectivity downstream of tanks/marsh; filled depressions assume micro-relief overflows. The 1 m limit is a configurable assumption, not a validated value.
- Coastal/tidal levels, rainfall, soil infiltration and channel/tank geometry are not modelled; D8 cannot represent divergent flow on flat terrain.
- TWI is a relative index; on very flat terrain it is unstable and sensitive to the slope clamp and to DEM noise.
- Independent reference data (e.g. mapped drains, surveyed flood points) were not used: the products are not validated.

## Outputs
Rasters in `data/processed`: dem_conditioned_utm44n_30m.tif, flow_direction_d8_utm44n_30m.tif, flow_accumulation_utm44n_30m.tif, drainage_network_utm44n_30m.tif, twi_utm44n_30m.tif, drainage_network_utm44n_30m.gpkg. Figures: flow_accumulation_map.png, drainage_network_map.png, dem_conditioning_difference.png, twi_map.png. Tables: hydrology_statistics.csv, hydrology_negative_clusters.csv, hydrology_depression_sensitivity.csv, hydrology_drainage_threshold_sensitivity.csv.
