# Sentinel-1 2021 date-level (multi-slice) coverage verification

METADATA / lightweight only. No flood classification, no flood extent, no baseline designation, no validation. The individual scene records in the inventory are unchanged; this is a separate summary.

- Input inventory (read only): `outputs/tables/s1_inventory_2021_nov_2021-09-01_2021-12-01.csv`; groups = (UTC date, pass, relative orbit, platform): 8 group(s), 16 slice(s).
- AOI: PROVISIONAL (provisional, not the official GCC boundary), area from footprints' CRS EPSG:32644 = 435.329 km2. AOI/query fingerprint `129aada1a243`; inventory fingerprint check: **MATCH**.
- Thresholds (documented defaults, adjustable): combined footprint >= 99.9 %, combined valid VV and VH >= 95.0 %.
- Earth Engine pixel/slice-metadata check: **RUN (this run)**. Query settings: {'collection': 'COPERNICUS/S1_GRD', 'instrumentMode': 'IW', 'platform_filter': None, 'valid_scale_m': 30, 'angle_scale_m': 100, 'coverage_geodesic_area': True, 'schema': 2}.
- Overlap is counted once: combined footprint = geometric union; combined valid share = pixels with data in >= 1 slice (image count > 0). Data bands are not zero-filled; only the per-pixel COUNT is unmasked so no-data pixels are counted as not covered.
- `valid` is the pixel-level (30 m sampling) measure; `footprint` is the product outline. Footprints are rounded to 5 decimal degrees in the inventory (~1 m).

## Explicit date checks

- **2021-11-16** (SENTINEL-1A DESCENDING rel orbit 92): 2 slice(s); combined footprint 100.0 %; gap 0.0 % (0.0 km2); overlap 0.0953 %; valid VV 99.998 %, VH 99.998 % -> **COMPLETE AOI COVERAGE (footprint and valid VV/VH)**.

## Per-date results

| date (UTC) | pass | rel orbit | platform | slices | slice cov % (inventory) | combined footprint % | overlap % | gap % | valid VV % | valid VH % | complete AOI | assessment |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021-09-05 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.780931074673806;79.31296622238052 | 100.0 | 0.0936 | 0.0 | 99.998 | 99.998 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |
| 2021-09-17 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.758193716513432;79.3360812404153 | 100.0 | 0.0929 | 0.0 | 99.997 | 99.997 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |
| 2021-09-29 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.782577263533895;79.31113770619645 | 100.0 | 0.0952 | 0.0 | 99.987 | 99.987 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |
| 2021-10-11 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.769895258686894;79.32467060549358 | 100.0 | 0.0904 | 0.0 | 99.988 | 99.988 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |
| 2021-10-23 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.800070551773192;79.29462304053268 | 100.0 | 0.0951 | 0.0 | 99.998 | 99.998 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |
| 2021-11-04 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.74570540600697;79.34793471267967 | 100.0 | 0.0941 | 0.0 | 99.999 | 99.999 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |
| 2021-11-16 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.76067446338597;79.33223630215547 | 100.0 | 0.0953 | 0.0 | 99.998 | 99.998 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |
| 2021-11-28 | DESCENDING | 92 | SENTINEL-1A | 2 | 20.758036101202826;79.33546148087277 | 100.0 | 0.0942 | 0.0 | 99.997 | 99.997 | yes | COMPLETE AOI COVERAGE (footprint and valid VV/VH) |

## Compatibility checks (True / False / None = not assessable from the data at hand)

| date | same group key | same pols | VV all | VH all | max slice time gap s | times compatible | same abs orbit | same CRS | same scale | same cycle | slice numbers consecutive | footprint cross-check pp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021-09-05 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.004 |
| 2021-09-17 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.005 |
| 2021-09-29 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.004 |
| 2021-10-11 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.007 |
| 2021-10-23 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.004 |
| 2021-11-04 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.003 |
| 2021-11-16 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.004 |
| 2021-11-28 | True | True | True | True | 25.0 | True | True | True | True | True | True | 0.004 |

## Reasons recorded


## Implementation note: is the existing mosaicking logic safe?

- Grouping key: acquisition (UTC) date, pass direction, relative orbit and platform (platform filter `platform_number` added in the M4-A review). Sentinel-1A/1B or different orbits/passes are never merged.
- `date_group_valid_pct` in the inventory is VV only, computed on a first-wins mosaic at 30 m. It is a screening number: no VH, no footprint union, gap or overlap, no compatibility checks. It is NOT sufficient to claim a complete AOI observation; this module adds those checks.
- A mosaic's value in an overlap strip comes from the first image in collection order. That does not affect coverage counts, but any later value-level preprocessing must define an explicit overlap rule (it must not be left to collection order).
- No result here is a flood, baseline or accuracy statement.
