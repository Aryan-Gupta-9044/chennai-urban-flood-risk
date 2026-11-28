# Sentinel-1 flood-extent workflow: technical review and the S1WC-1 candidate product

## 1. Review of the existing scripts
**`scripts/s1_flood_extent.py`** – pre/post change detection (`post - pre < -3 dB` and `post < -15 dB`, slope mask). Earth Engine path or `--local` path on pre/post GeoTIFFs. Does not read the processed 2021 per-date rasters.
**`scripts/s1b_flood_extent.py`** – pinned 2015 scenes, Earth Engine verification gate, 10 m, VV only. Duplicates most of the first script's logic with different constants; shares the status ID "S1B".

Defects: shared status ID and `COMPLETED` for an unvalidated proxy; unhashed inputs, silent overwrites in shared folders; missing slope treated as 0; nearest-neighbour sub-sampling (EE path) and bilinear regridding in the dB domain (local path); no permanent-water/pre-dark exclusion in the local path; legend calls invalid/unassessed pixels "No flood detected"; VV only (s1b); hard-coded 2015 text; Earth Engine paths cannot be tested offline.
Methodological limits: a pre/post pair needs a defensible pre-event scene (none is designated for 2021), dB offsets of 2-3 dB between dates (measured here) move a fixed threshold, no shadow/layover model, no independent reference.

**Retained:** neither script as the product. Their change-detection idea is kept only as a documented concept; both stay untouched. The additive `s1_water_candidates_review.py` reads the processed 2021 products and is offline.

## 2. What S1WC-1 does
Per acquisition date: valid(VV and VH) -> dual-pol dark (VV < -18, VH < -24 dB) -> persistence screen from the same stack (dark on >= 6 of >= 6 valid dates) -> slope screen (> 5 deg) -> 8-neighbour cluster >= 4 cells. Class codes: 0 valid not dark, 1 transient dark candidate, 2 persistently dark, 3 slope-excluded, 4 small cluster, 5 VV-only dark, 6 persistence unassessable, 7 slope unknown, 254 invalid inside AOI, 255 outside AOI.
Cross-date rasters: `n_valid_dates`, `n_dark_dates`, `persistent_dark_mask`, `transient_candidate_date_count` (a COUNT OF DATES, not an event extent).
Tables: class counts, threshold sensitivity (nothing selected from it), date-level radiometric shift (diagnostic, nothing normalised), terrain/hydrology context (descriptive), input QA, CHIRPS join (context only).

## 3. Can / cannot claim
Can: provisional S1-derived dark-backscatter water candidates per acquisition date on the master grid, with explicit unknown classes, reproducible, inputs hash-verified.
Wording: low backscatter is a common indicator of smooth open water, but neither necessary nor sufficient.
Cannot: a flood extent, an event map, validated or independent; any accuracy/precision/recall/F1/IoU; that dark = water; that flooded vegetation/urban is captured; that persistent-dark = permanent water.

## 4. Run
```
.\.venv\Scripts\python scripts\s1_water_candidates_review.py
.\.venv\Scripts\python scripts\s1_water_candidates_review.py --outdir outputs\s1_water_candidates_review_v1 --no-rainfall
```
Output goes to a new directory; the run stops if any planned output exists, if the directory overlaps the inputs, `outputs/reports|tables|figures`, or an `s1_2021_persistence*`/`chirps_2021*` family. Exit codes: 0 ok, 2 stopped before writing, 3 input hash changed.
Thresholds live in `config/s1_water_candidates.json` and are starting values, not tuned or validated for Chennai.
