# CHIRPS v3 DAILY_SAT vs IMD 0.25 deg - side-by-side comparison

**Not a validation.** Neither product is ground truth; CHIRPS blends station data (so it is not independent of gauges); the two products use different, unverified day definitions. They are never merged, gap-filled or blended here.

## IMD coverage of the Chennai AOI (documented, not repaired)
- IMD native cells overlapping the AOI: 3; with any valid data in the window: 1. AOI-area share covered by valid IMD cells per day: min 28.1%, max 28.1%.
- Per-cell table: `outputs/tables/chirps_vs_imd_support.csv`. IMD cells without data are NOT filled from CHIRPS.

## Spatial support
- CHIRPS AOI support: 100% of the AOI polygon lies inside the CHIRPS export window (153 of 153 CHIRPS days present, 153 IMD days present).
- CHIRPS is area-averaged over an IMD cell footprint (comparison only; no resampling of either product). 'footprint' needs the export window to cover the 0.25 deg cell; 'aoi_part' averages CHIRPS over (IMD cell ∩ AOI), always supported but a different spatial support from the IMD value.

## Daily timing (1-2 December 2015 and lags)
Documented/expected day conventions (UNVERIFIED for these exact products): IMD - 24 h accumulation ending 08:30 IST, label convention (end vs start date) not confirmed; CHIRPS v3 SAT - daily labels from the IMERG-based disaggregation, expected UTC-day based (00-24 UTC = 05:30-05:30 IST) but NOT verified as local observation days. Candidate explanations to test (none established): (1) end-date vs start-date labelling of IMD; (2) the ~3 h offset between the 08:30 IST and 05:30 IST day boundaries; (3) the IMERG disaggregation of station pentads; (4) IMD gauge interpolation onto one valid cell. The lag table and the two-day-sum row below are diagnostics only.

- IMD cell r101c55 / footprint: IMD 1 Dec 72.3, 2 Dec 329.3 (sum 401.6); CHIRPS 1 Dec 198.6, 2 Dec 31.4 (sum 230.0); 2-day-sum ratio CHIRPS/IMD 0.6
- IMD cell r101c55 / aoi_part: IMD 1 Dec 72.3, 2 Dec 329.3 (sum 401.6); CHIRPS 1 Dec 202.2, 2 Dec 30.0 (sum 232.1); 2-day-sum ratio CHIRPS/IMD 0.6

Lag statistics (IMD[d] vs CHIRPS[d+k]) for the context window and the provisional focus window 2015-11-20..2015-12-06: `outputs/tables/chirps_vs_imd_lags.csv` (r needs >= 8 pairs).

Conclusion rule: until the day windows are verified, daily CHIRPS values must NOT be used as precise antecedent rainfall relative to a ~06:01 IST Sentinel-1 pass; use multi-day totals with the timing uncertainty stated.

## Files
- outputs/tables/chirps_vs_imd_{support,daily,lags,dec1_2}.csv
- outputs/figures/chirps_vs_imd_timeseries.png
- outputs/figures/chirps_vs_imd_lag_correlation.png
