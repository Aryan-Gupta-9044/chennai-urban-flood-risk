# Sentinel-1 2021-11-04 QA diagnostics (M4C single-date review)

READ-ONLY diagnostics of the existing products. No value was clamped, removed or masked; the original rasters are unchanged (SHA-256 of the six product files compared before/after: **identical**). Not a flood analysis, not a baseline, not validation.

- Scenes: `S1A_IW_GRDH_1SDV_20211104T003147_20211104T003212_040414_04CA78_AD56`, `S1A_IW_GRDH_1SDV_20211104T003212_20211104T003237_040414_04CA78_20F6`. AOI: PROVISIONAL (provisional). Product grid EPSG:32644 30 m, default `linear_area_mean`.

## 1. VV above +5 dB

- Cells: **43726** = **9.0394 %** of AOI cells (9.0396 % of valid AOI cells).
- Connected components (8-neighbour): **7968**; largest 441 cells (0.3969 km2); median 2.0 cells; single-cell components 3258; share of flagged cells in components of >= 10 cells: 60.13 %.
- Component size histogram (cells): {"1-1": 3258, "2-4": 2908, "5-9": 1008, "10-49": 677, "50-199": 100, "200-inf": 17}.
- Spatial distribution: see `outputs/tables/s1_2021_2021-11-04_VV_high_blocks.csv` and the map `outputs/figures/s1_2021_2021-11-04_VV_high_map.png`; components with coordinates in `outputs/tables/s1_2021_2021-11-04_VV_high_components.csv`.

### Exceedance at several cut-offs (no single cut-off is implied)

| pol | threshold dB | cells | % of AOI cells | % of valid AOI cells |
|---|---|---|---|---|
| VV | +0 | 133059 | 27.507 | 27.5077 |
| VV | +3 | 72004 | 14.8853 | 14.8856 |
| VV | +5 | 43726 | 9.0394 | 9.0396 |
| VV | +8 | 17789 | 3.6775 | 3.6776 |
| VV | +10 | 8886 | 1.837 | 1.837 |
| VH | +0 | 683 | 0.1412 | 0.1412 |
| VH | +3 | 256 | 0.0529 | 0.0529 |
| VH | +5 | 143 | 0.0296 | 0.0296 |
| VH | +8 | 56 | 0.0116 | 0.0116 |
| VH | +10 | 35 | 0.0072 | 0.0072 |

### Is the tail created by the 10 m -> 30 m aggregation? (from this date's metadata, server-side AOI statistics at 30 m)

| option | VV mean dB | VV p95 dB | VV std dB |
|---|---|---|---|
| point_db | -3.5784 | 6.8737 | 6.016 |
| linear_area_mean | -3.0127 | 7.1271 | 5.7969 |
| linear_area_mean_focal_median | -3.1534 | 5.6259 | 5.2374 |

If the unfiltered `point_db` option already has a similar p95, the bright tail is present before the linear block mean (aggregation is not what creates it). Linear averaging does weight bright scatterers more than a dB average, so the two can differ.

### Association (descriptive, not causal)

- VH at the high-VV cells: mean -11.8693 dB versus -13.8148 dB elsewhere.
- Seam zone: 243 high cells inside the seam zone, which is 0.6756 % of the AOI; high share within the zone 7.4609 % vs 9.0396 % overall.

- WorldCover / slope rasters not found in data/processed: association with land cover and slope NOT assessed.

- Mean slope at high cells 2.0423 deg vs 1.9706 deg elsewhere (DEM-derived, 30 m).

**Interpretation limits.** Nothing here shows these values are errors, and nothing shows they are correct. Backscatter above 0 dB is commonly reported over dense built-up surfaces (corner/double-bounce reflectors) and the product is not radiometrically terrain-flattened, so slope-facing surfaces can also be bright; these are hypotheses to test against the class/slope association above and the preview, not findings. No clamping, masking or removal is applied or recommended on this evidence alone.

## 2. Overlap reconciliation: three different things

| notion | defined by | value for this date |
|---|---|---|
| acquisition-time overlap | scene ids (start/stop): first slice stops 2021-11-04T00:32:12+00:00, second starts 2021-11-04T00:32:12+00:00 | gap = 0.0 s; same data take: True |
| footprint (outline) overlap, M4B | intersection of slice footprint polygons inside the AOI | 0.0941 % of AOI = 0.4097 km2 (M4B file); local recomputation: area 409694.9053 m2, sliver width ~35.1643 m, length ~11775.7413 m |
| valid per-pixel overlap, M4C | cells (10 m UTM lattice) where BOTH slices have data in the AOI | VV 0 px, VH 0 px |

- The scene ids show a shared cut time (2021-11-04T00:32:12+00:00, gap 0 s): the two slices are consecutive parts of one data take. This module does not assume that adjacent slices must, or must not, share pixels; the pixel overlap is reported as measured above.
- The footprint-overlap sliver is ~35.2 m wide (about 4097 10 m cells if it were data), WIDER than one pixel, yet 0 valid overlapping pixels were found: this is NOT explained by sub-pixel width. Possible: the footprint outline includes border/no-data margins that carry no valid pixels. Not confirmed - inspect the slice edges.
- Gap check across the seam: seam-zone cells 3268; minimum valid fraction 0.4444; cells with valid fraction < 1: 467; valid share of the zone 99.6634 %. Whole-AOI valid share at 10 m: 0.9997.
- The overlap rule (linear-power mean of valid slices) is unchanged and was not forced to overlap anything; with zero overlapping valid pixels every output cell comes from exactly one slice.
