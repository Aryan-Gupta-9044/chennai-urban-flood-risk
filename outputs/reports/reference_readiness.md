# Independent-reference data-readiness matrix

Nothing below has been downloaded or verified by SHIVE. UNCONFIRMED = not established.

| dataset | obs. date | sensor/source | independent of S1 | format | CRS | extent | access | licence | readiness |
|---|---|---|---|---|---|---|---|---|---|
| ALOS-2/PALSAR-2 flood extent | 2015-12-03 | L-band SAR (not Sentinel-1) | True | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | NOT YET OBTAINED | UNCONFIRMED | NOT YET OBTAINED; suitability cannot be assessed until obtained (unconfirmed: format, crs, extent, kind, licence) |
| RISAT-1 flood products | 2015-12-03, 2015-12-04, 2015-12-06 | C-band SAR (not Sentinel-1) | True | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | NOT YET OBTAINED | UNCONFIRMED | NOT YET OBTAINED; suitability cannot be assessed until obtained (unconfirmed: format, crs, extent, kind, licence) |
| RADARSAT-2 flood/recession product | 2015-12-04 | C-band SAR (not Sentinel-1) | True | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | NOT YET OBTAINED | UNCONFIRMED | NOT YET OBTAINED; suitability cannot be assessed until obtained (unconfirmed: format, crs, extent, kind, licence) |
| NRSC / Bhuvan / NDEM inundation products | UNCONFIRMED | UNCONFIRMED | None | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | NOT YET OBTAINED | UNCONFIRMED | NOT YET OBTAINED; suitability cannot be assessed until obtained (unconfirmed: format, crs, extent, kind, licence, obs_date) |
| UNOSAT and IWMI November flood products | UNCONFIRMED (November 2015) | Sentinel-1 derived (per project notes) | False | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | NOT YET OBTAINED | UNCONFIRMED | NOT SUITABLE FOR QUANTITATIVE VALIDATION (Sentinel-1-derived: not independent of a Sentinel-1 proxy; usable only as a consistency comparison) |
| Published Adyar basin flood-depth observations | UNCONFIRMED | field / survey observations | True | UNCONFIRMED | UNCONFIRMED | Adyar basin only (partial AOI) | NOT YET OBTAINED | UNCONFIRMED | NOT YET OBTAINED; suitability cannot be assessed until obtained (unconfirmed: format, crs, licence, obs_date) |
| OpenCity / GCC flood points | UNCONFIRMED | administrative / crowd-reported points | True | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | NOT YET OBTAINED | UNCONFIRMED | NOT YET OBTAINED; suitability cannot be assessed until obtained (unconfirmed: format, crs, extent, licence, obs_date) |

## Technical requirements before any dataset is used for comparison

- georeferenced raster or vector with a stated CRS (a PDF/JPEG map is qualitative until georeferenced; digitising adds its own error)
- stated observation date/time (and time of day) distinct from the Sentinel-1 acquisition date
- spatial extent covering the study area, or a documented partial extent
- documented class meaning (flooded / not flooded / unknown / permanent water / no data)
- documented production method, so independence from Sentinel-1 can be judged
- licence permitting use and redistribution of derived statistics
- known or estimated positional accuracy

Comparison against any reference yields AGREEMENT metrics only; it is not accuracy unless the reference quality is established.