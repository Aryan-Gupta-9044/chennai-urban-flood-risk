# CHIRPS v3 DAILY_SAT coverage probe (chirps_v3_sat)

**Verdict: PROCEED-TO-REVIEW** (the user still has to review this before the bulk download is built)

## Status
- Earth Engine calls: executed by this run on your machine (the build sandbox could not run them). Helper logic is unit-tested on synthetic arrays only.
- Not validated. Not a flood-prediction result. SAT is IMERG-split but CHIRPS blends station data, so it is not independent of gauges.

## Collection and grid
- Dataset `UCSB-CHC/CHIRPS/V3/DAILY_SAT`; bands ['precipitation']; band `precipitation` metadata: {"id": "precipitation", "data_type": {"type": "PixelType", "precision": "float"}, "dimensions": [7200, 2400], "crs": "EPSG:4326", "crs_transform": [0.05000000074505806, 0, -180, 0, -0.05000000074505806, 60]}
- Native projection reported by Earth Engine: crs `EPSG:4326`, transform `[0.05000000074505806, 0.0, -180.0, 0.0, -0.05000000074505806, 60.0]`, nominal scale 5566.0 m. Native pixel size used for every export; no reproject, no resample.
- Images in window 2015-07-21..2015-12-20: 153; dates found 153 / expected 153; missing 0; duplicated 0; unexpected 0
- Timestamps not at 00:00:00 UTC: 0 []; year/month/day property mismatches: 0 []
- Units: catalog says mm/d (not independently checkable from pixel values).

## Study-area coverage (actual polygon, exact cell intersection)
- Polygon cells touching the AOI: 29 (native cells, window 10x7 incl. 1-cell pad). The polygon lies fully inside the window (share 1.0000).
- Measure 1 - AOI area coverage: share of the polygon's area covered by valid CHIRPS pixels (threshold 95%).
- Measure 2 - Daily temporal completeness: % of the 153 dates meeting that threshold: **100.0% (153/153) - server-side, verified against the exported test images**.

### Export request used (native-grid window)
- `crs`=EPSG:4326, `crs_transform`=[0.05000000074505806, 0.0, 80.05000387504697, 0.0, -0.05000000074505806, 13.299999304115772], `dimensions`=[7, 10] (width, height); no `region`, no `scale`. Expected window bounds [80.05000387504697, 12.799999296665192, 80.40000388026237, 13.299999304115772].
- Earth Engine implements this as a re-grid onto the SAME 0.05 degree lattice (offset by whole cells); values are checked against native cell-centre samples, not assumed identical.

### Exported test images (actual files in data/external/rainfall/chirps_v3_daily/probe/)
| date | AOI area coverage | valid cells | missing cells | zero-mm valid cells | sentinel cells |
|---|---|---|---|---|---|
| 2015-07-21 | 100.0% | 29/29 | 0 | 34 | 3 |
| 2015-11-15 | 100.0% | 29/29 | 0 | 0 | 3 |
| 2015-12-01 | 100.0% | 29/29 | 0 | 0 | 3 |
| 2015-12-20 | 100.0% | 29/29 | 0 | 8 | 3 |

NoData handling: masked pixels were exported as -9999 together with an explicit 0/1 valid band; consistency check = valid band is 0/1, every masked cell holds -9999, no valid cell holds -9999, no NaN, no negative rainfall, plus a server-side sample at cell centres. Genuine 0 mm in valid cells is counted separately and kept as 0.

Server (EE weighted-mean mask) vs local exact-geometry coverage on test dates: 2015-07-21: 1.0 vs 1.0000; 2015-11-15: 1.0 vs 1.0000; 2015-12-01: 1.0 vs 1.0000; 2015-12-20: 1.0 vs 1.0000

Per-date table (valid/missing cells for every date): `outputs/tables/chirps_v3_sat_probe_dates.csv`. Dates below threshold: 0 []

## Caveats (recorded, not resolved)
- Day definition: PROVISIONAL / NOT VERIFIED: CHIRPS v3 daily values are pentad totals split into days using IMERG Late V07 (SAT). Daily date labels are consistent labels from that disaggregation, NOT verified local (IST) observation-day windows.
- Licence: DISCREPANCY: Earth Engine catalog says public domain (CC0-style waiver); CHC page says CC BY 4.0. Attribute under CC BY 4.0 (stricter). Citation: Climate Hazards Center Infrared Precipitation with Stations version 3, CHIRPS3 Data Repository, doi:10.15780/G2JQ0P (2025); Funk et al. (2026) Sci Data 13, 718, doi:10.1038/s41597-026-07096-4.
- References: gee_catalog: https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHC_CHIRPS_V3_DAILY_SAT; chc_page: https://chc.ucsb.edu/node/497; chc_archive: https://data.chc.ucsb.edu/products/CHIRPS/v3.0/; chc_daily_readme: https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/readme.txt
- DAILY_RNL (ERA5-split) was NOT examined or used; its catalog metadata must be verified separately before any later sensitivity run. SAT and RNL are never combined.
- Outputs are kept apart from IMD (data/external/rainfall/chirps_v3_daily/ vs imd_gridded_daily/).

## Provenance of this run
- Test rasters: 2015-07-21: REUSED from an earlier run's download (re-validated in full this run; not downloaded again); 2015-11-15: REUSED from an earlier run's download (re-validated in full this run; not downloaded again); 2015-12-01: REUSED from an earlier run's download (re-validated in full this run; not downloaded again); 2015-12-20: REUSED from an earlier run's download (re-validated in full this run; not downloaded again)
- Per-date server results: computed this run
- Output-writing failures: none
