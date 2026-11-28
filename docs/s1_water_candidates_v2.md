# S1WC-2: additive refinement of the S1WC-1 dark-backscatter candidate product

S1WC-1 code, config, outputs and all source data are unchanged. S1WC-2 is a separate version with its own output directory (`outputs/s1_water_candidates_review_v2/`).

## What changed
One new class. **Class 8 = dark candidate on a provisional DEM-indicated flattened-water signature.** It is carved only out of S1WC-1 class 1, so on every date class1(S2) + class8(S2) = class1(S1WC-1) and all other classes (0, 2-7, 254, 255) are identical. The pipeline verifies this on every run (and against the stored S1WC-1 class rasters when `--s1wc1-dir` is available; a mismatch stops the run).

## Signature (provisional)
DEM == 0 exactly, OR a non-zero constant-elevation plateau: a 4-neighbour component of exactly equal DEM values on the 30 m master grid with >= 30 cells (`min_plateau_cells`, fixed a priori; 10/20/50 are reported as sensitivity only). A generic slope == 0 rule is **not** used (61 slope-0 cells with DEM > 0 are deliberately not flagged on the real data). It is **not** a confirmed permanent-water mask, **not** a flood exclusion, and **not** the Copernicus Water Body Mask (not used). Copernicus GLO-30 flattens water bodies and a DEM value of 0 does not imply mean sea level. Plateau detection sees only the AOI (DEM is NoData outside).

## Added outputs
8 per-date class rasters; signature raster (0 none, 1 DEM=0, 2 plateau, 255 outside); class-1 and class-8 date-count rasters (counts of dates, not event maps); before/after counts; class counts; comparability table (stable VV/VH shift, VV-VH, block spread next to the counts); signature summary and plateau-size sensitivity; TWI-clamp summary; terrain context with clamp-excluded variants; input QA; regression table; report; manifest with input and **output** SHA-256 and the caveats.

## Not changed / not done
No radiometric normalisation, no new threshold, no terrain flattening, no flood label, no WBM. Remaining class-1 cells are **not confirmed floodwater**; class-8 cells are not confirmed permanent water. Date-level radiometric offsets mean counts are not comparable across dates.

## Run (PowerShell, repo root)
```
.\.venv\Scripts\python scripts\s1_water_candidates_v2_review.py
.\.venv\Scripts\python scripts\s1_water_candidates_v2_review.py --outdir outputs\s1_water_candidates_review_v2 --s1wc1-dir outputs\s1_water_candidates_review_v1
```
Exit codes: 0 ok, 2 stopped before writing (missing input, grid mismatch, existing outputs, overlap with inputs / S1WC-1 / shared output folders / protected output families, S1WC-1 mismatch), 3 an input hash changed. Run without `--allow-missing-metadata` when the sidecars exist.
