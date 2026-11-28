# CHIRPS v3 DAILY_SAT acquisition report

**Result: COMPLETE** - 153 of 153 dates in 2015-07-21..2015-12-20 accepted (integrity + >= 95% AOI-area coverage).

## Integrity
- Dataset `UCSB-CHC/CHIRPS/V3/DAILY_SAT` (variant DAILY_SAT); DOI 10.15780/G2JQ0P; retrieval started 2026-11-23T11:52:08+00:00 UTC.
- Grid: EPSG:4326, native pixel 0.05000000074505806 deg (nominal 0.05; Earth Engine reports 0.0500000007), export window 10x7 native cells (a clipped window of the native grid, NOT a resample); AOI-intersecting cells 29.
- Every accepted file passed: 2 bands, native CRS/pixel size/lattice alignment/window origin/shape, valid band 0/1, masked cells = -9999 only, no NaN, no negative rainfall, and a server cell-centre sample agreeing with the file.
- AOI-area coverage over accepted dates: min 100.0%, max 100.0%.
- Checksums: `data/external/rainfall/chirps_v3_daily/raw/SHA256SUMS.txt` and `download_manifest.json` (per-date attempts, HTTP status, sha256, request fields, validation). Per-date table: `outputs/tables/chirps_v3_sat_acquisition.csv`.

## Limitations (unchanged by acquisition)
- Day definition: PROVISIONAL / NOT VERIFIED: CHIRPS v3 daily values are pentad totals split into days using IMERG Late V07 (SAT). Daily date labels are consistent labels from that disaggregation, NOT verified local (IST) observation-day windows.
- Licence: DISCREPANCY: Earth Engine catalog says public domain (CC0-style waiver); CHC page says CC BY 4.0. Attribute under CC BY 4.0 (stricter). Citation: Climate Hazards Center Infrared Precipitation with Stations version 3, CHIRPS3 Data Repository, doi:10.15780/G2JQ0P (2025); Funk et al. (2026) Sci Data 13, 718, doi:10.1038/s41597-026-07096-4.
- SAT is IMERG-split but CHIRPS itself blends station data, so it is not independent of gauge observations. Not validated.
- Native 0.05 deg (about 5.5 km): the AOI spans 29 cells; this adds no finer spatial information. No resampling was done.
- Not validated; not a flood-prediction result. Event window remains PROVISIONAL.
