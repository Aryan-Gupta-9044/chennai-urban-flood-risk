# Sentinel-1 2021-11-28 QA diagnostics (M4C single-date review)

READ-ONLY diagnostics of the existing products. No value was clamped, removed or masked; the original rasters are unchanged (SHA-256 of the six product files compared before/after: **identical**). Not a flood analysis, not a baseline, not validation.

- Scenes: `S1A_IW_GRDH_1SDV_20211128T003147_20211128T003212_040764_04D697_BA95`, `S1A_IW_GRDH_1SDV_20211128T003212_20211128T003237_040764_04D697_A118`. AOI: PROVISIONAL (provisional). Product grid EPSG:32644 30 m, default `linear_area_mean`.

## 1. VV above +5 dB

- Cells: **42996** = **8.8885 %** of AOI cells (8.8885 % of valid AOI cells).
- Connected components (8-neighbour): **8355**; largest 414 cells (0.3726 km2); median 2.0 cells; single-cell components 3418; share of flagged cells in components of >= 10 cells: 57.24 %.
- Component size histogram (cells): {"1-1": 3418, "2-4": 3108, "5-9": 1044, "10-49": 675, "50-199": 100, "200-inf": 10}.
- Spatial distribution: see `outputs/tables/s1_2021_2021-11-28_VV_high_blocks.csv` and the map `outputs/figures/s1_2021_2021-11-28_VV_high_map.png`; components with coordinates in `outputs/tables/s1_2021_2021-11-28_VV_high_components.csv`.

### Exceedance at several cut-offs (no single cut-off is implied)

| pol | threshold dB | cells | % of AOI cells | % of valid AOI cells |
|---|---|---|---|---|
| VV | +0 | 133494 | 27.597 | 27.5971 |
| VV | +3 | 71507 | 14.7825 | 14.7826 |
| VV | +5 | 42996 | 8.8885 | 8.8885 |
| VV | +8 | 17421 | 3.6014 | 3.6014 |
| VV | +10 | 8899 | 1.8397 | 1.8397 |
| VH | +0 | 705 | 0.1457 | 0.1457 |
| VH | +3 | 279 | 0.0577 | 0.0577 |
| VH | +5 | 139 | 0.0287 | 0.0287 |
| VH | +8 | 52 | 0.0107 | 0.0107 |
| VH | +10 | 32 | 0.0066 | 0.0066 |

### Is the tail created by the 10 m -> 30 m aggregation? (from this date's metadata, server-side AOI statistics at 30 m)

| option | VV mean dB | VV p95 dB | VV std dB |
|---|---|---|---|
| point_db | -3.7319 | 6.7436 | 6.2395 |
| linear_area_mean | -3.1427 | 6.8734 | 6.0126 |
| linear_area_mean_focal_median | -3.2872 | 5.626 | 5.4448 |

If the unfiltered `point_db` option already has a similar p95, the bright tail is present before the linear block mean (aggregation is not what creates it). Linear averaging does weight bright scatterers more than a dB average, so the two can differ.

### Association (descriptive, not causal)

- VH at the high-VV cells: mean -11.8031 dB versus -13.9021 dB elsewhere.
- Seam zone: 265 high cells inside the seam zone, which is 0.676 % of the AOI; high share within the zone 8.1114 % vs 8.8885 % overall.

- WorldCover / slope rasters not found in data/processed: association with land cover and slope NOT assessed.

- Mean slope at high cells 2.0023 deg vs 1.9747 deg elsewhere (DEM-derived, 30 m).

**Interpretation limits.** Nothing here shows these values are errors, and nothing shows they are correct. Backscatter above 0 dB is commonly reported over dense built-up surfaces (corner/double-bounce reflectors) and the product is not radiometrically terrain-flattened, so slope-facing surfaces can also be bright; these are hypotheses to test against the class/slope association above and the preview, not findings. No clamping, masking or removal is applied or recommended on this evidence alone.

## 2. Overlap reconciliation: three different things

| notion | defined by | value for this date |
|---|---|---|
| acquisition-time overlap | scene ids (start/stop): first slice stops 2021-11-28T00:32:12+00:00, second starts 2021-11-28T00:32:12+00:00 | gap = 0.0 s; same data take: True |
| footprint (outline) overlap, M4B | intersection of slice footprint polygons inside the AOI | 0.0942 % of AOI = 0.4099 km2 (M4B file); local recomputation: area 409934.9335 m2, sliver width ~35.0806 m, length ~11778.5161 m |
| valid per-pixel overlap, M4C | cells (10 m UTM lattice) where BOTH slices have data in the AOI | VV 0 px, VH 0 px |

- The scene ids show a shared cut time (2021-11-28T00:32:12+00:00, gap 0 s): the two slices are consecutive parts of one data take. This module does not assume that adjacent slices must, or must not, share pixels; the pixel overlap is reported as measured above.
- The footprint-overlap sliver is ~35.1 m wide (about 4099 10 m cells if it were data), WIDER than one pixel, yet 0 valid overlapping pixels were found: this is NOT explained by sub-pixel width. Possible: the footprint outline includes border/no-data margins that carry no valid pixels. Not confirmed - inspect the slice edges.
- Gap check across the seam: seam-zone cells 3270; minimum valid fraction 0.4444; cells with valid fraction < 1: 464; valid share of the zone 99.9083 %. Whole-AOI valid share at 10 m: 0.9997.
- The overlap rule (linear-power mean of valid slices) is unchanged and was not forced to overlap anything; with zero overlapping valid pixels every output cell comes from exactly one slice.
