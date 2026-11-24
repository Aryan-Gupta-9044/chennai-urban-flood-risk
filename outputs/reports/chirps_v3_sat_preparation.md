# CHIRPS v3 DAILY_SAT - preparation for rainfall_workflow

- Converted 153 of 153 dates (2015-07-21..2015-12-20); of these 0 are LOW_COVERAGE dates converted only because --include-low-coverage was set. Raw files untouched in `raw/`.
- Daily files keep the raw CRS and transform exactly (native 0.05 deg window; no resample, no reproject). Masked cells = -9999; genuine 0 mm = 0.
- Not converted (0): none
- Day definition: PROVISIONAL / NOT VERIFIED: CHIRPS v3 daily values are pentad totals split into days using IMERG Late V07 (SAT). Daily date labels are consistent labels from that disaggregation, NOT verified local (IST) observation-day windows.
- SAT is IMERG-split but CHIRPS itself blends station data, so it is not independent of gauge observations. Not validated.

Next: `python scripts/rainfall_workflow.py --source-id chirps_v3_daily --event 2015_nov_dec`
