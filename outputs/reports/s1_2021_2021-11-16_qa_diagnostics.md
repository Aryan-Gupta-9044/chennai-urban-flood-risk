# Sentinel-1 2021-11-16 QA diagnostics (M4C single-date review)

READ-ONLY diagnostics of the existing products. No value was clamped, removed or masked; the original rasters are unchanged (SHA-256 of the six product files compared before/after: **identical**). Not a flood analysis, not a baseline, not validation.

- Scenes: `S1A_IW_GRDH_1SDV_20211116T003147_20211116T003212_040589_04D094_DB41`, `S1A_IW_GRDH_1SDV_20211116T003212_20211116T003237_040589_04D094_B07B`. AOI: PROVISIONAL (provisional). Product grid EPSG:32644 30 m, default `linear_area_mean`.

## 1. VV above +5 dB

- Cells: **22343** = **4.6189 %** of AOI cells (4.6189 % of valid AOI cells).
- Connected components (8-neighbour): **7796**; largest 136 cells (0.1224 km2); median 2.0 cells; single-cell components 3610; share of flagged cells in components of >= 10 cells: 26.02 %.
- Component size histogram (cells): {"1-1": 3610, "2-4": 3104, "5-9": 777, "10-49": 294, "50-199": 11, "200-inf": 0}.
- Spatial distribution: see `outputs/tables/s1_2021_2021-11-16_VV_high_blocks.csv` and the map `outputs/figures/s1_2021_2021-11-16_VV_high_map.png`; components with coordinates in `outputs/tables/s1_2021_2021-11-16_VV_high_components.csv`.

### Exceedance at several cut-offs (no single cut-off is implied)

| pol | threshold dB | cells | % of AOI cells | % of valid AOI cells |
|---|---|---|---|---|
| VV | +0 | 92803 | 19.185 | 19.185 |
| VV | +3 | 42170 | 8.7177 | 8.7177 |
| VV | +5 | 22343 | 4.6189 | 4.6189 |
| VV | +8 | 7891 | 1.6313 | 1.6313 |
| VV | +10 | 3935 | 0.8135 | 0.8135 |
| VH | +0 | 542 | 0.112 | 0.112 |
| VH | +3 | 212 | 0.0438 | 0.0438 |
| VH | +5 | 112 | 0.0232 | 0.0232 |
| VH | +8 | 49 | 0.0101 | 0.0101 |
| VH | +10 | 25 | 0.0052 | 0.0052 |

### Is the tail created by the 10 m -> 30 m aggregation? (from this date's metadata, server-side AOI statistics at 30 m)

| option | VV mean dB | VV p95 dB | VV std dB |
|---|---|---|---|
| point_db | -5.044 | 4.7477 | 5.8451 |
| linear_area_mean | -4.4775 | 4.8741 | 5.5893 |
| linear_area_mean_focal_median | -4.6228 | 3.1246 | 4.992 |

If the unfiltered `point_db` option already has a similar p95, the bright tail is present before the linear block mean (aggregation is not what creates it). Linear averaging does weight bright scatterers more than a dB average, so the two can differ.

### Association (descriptive, not causal)

- VH at the high-VV cells: mean -11.9093 dB versus -14.5141 dB elsewhere.
- Seam zone: 129 high cells inside the seam zone, which is 0.6768 % of the AOI; high share within the zone 3.9401 % vs 4.6189 % overall.

- WorldCover / slope rasters not found in data/processed: association with land cover and slope NOT assessed.

- Mean slope at high cells 2.0277 deg vs 1.9747 deg elsewhere (DEM-derived, 30 m).

**Interpretation limits.** Nothing here shows these values are errors, and nothing shows they are correct. Backscatter above 0 dB is commonly reported over dense built-up surfaces (corner/double-bounce reflectors) and the product is not radiometrically terrain-flattened, so slope-facing surfaces can also be bright; these are hypotheses to test against the class/slope association above and the preview, not findings. No clamping, masking or removal is applied or recommended on this evidence alone.

## 2. Overlap reconciliation: three different things

| notion | defined by | value for this date |
|---|---|---|
| acquisition-time overlap | scene ids (start/stop): first slice stops 2021-11-16T00:32:12+00:00, second starts 2021-11-16T00:32:12+00:00 | gap = 0.0 s; same data take: True |
| footprint (outline) overlap, M4B | intersection of slice footprint polygons inside the AOI | 0.0953 % of AOI = 0.4147 km2 (M4B file); local recomputation: area 414675.3448 m2, sliver width ~35.617 m, length ~11779.6644 m |
| valid per-pixel overlap, M4C | cells (10 m UTM lattice) where BOTH slices have data in the AOI | VV 0 px, VH 0 px |

- The scene ids show a shared cut time (2021-11-16T00:32:12+00:00, gap 0 s): the two slices are consecutive parts of one data take. This module does not assume that adjacent slices must, or must not, share pixels; the pixel overlap is reported as measured above.
- The footprint-overlap sliver is ~35.6 m wide (about 4147 10 m cells if it were data), WIDER than one pixel, yet 0 valid overlapping pixels were found: this is NOT explained by sub-pixel width. Possible: the footprint outline includes border/no-data margins that carry no valid pixels. Not confirmed - inspect the slice edges.
- Gap check across the seam: seam-zone cells 3274; minimum valid fraction 0.5556; cells with valid fraction < 1: 441; valid share of the zone 100.0 %. Whole-AOI valid share at 10 m: 0.9997.
- The overlap rule (linear-power mean of valid slices) is unchanged and was not forced to overlap anything; with zero overlapping valid pixels every output cell comes from exactly one slice.
