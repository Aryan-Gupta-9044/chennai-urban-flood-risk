# Flood-reference integration R0-R2 v1.2: implementation report

**Software validation is not flood-map accuracy validation.** Nothing here makes a file an authoritative flood reference, creates a flood label, or computes an agreement/accuracy metric. R3-R5 are not started.

## v1.2 correction
The v1.1 report said outputs matching `outputs/s1_2021_persistence*` were protected, but the code protected only `s1_2021_persistence` and `s1_2021_persistence_v1_2`. Now an output directory is rejected if it is, contains or lies inside ANY existing `outputs/s1_2021_persistence*` directory, OR lies in that reserved top-level namespace even if the directory does not exist yet (e.g. `_v1_3`, `_backup`, any suffix; case-insensitive). The prefix reserves only top-level `outputs/s1_2021_persistence*`; a nested folder such as `outputs/flood_reference_readiness/s1_2021_persistence_x` is allowed. Existing protections (outputs, reports, tables, figures, maps, CHIRPS 2021, the reference's own folder) are unchanged. Tests: `TestV12PersistenceNamespace` (4). Nothing else changed.

## v1.1 corrections (previous release; v1 review items 1-4)
| # | Issue in v1 | Fix in v1.1 | Tests |
|---|---|---|---|
| 1 | NaN / +inf / -inf counted as valid raster cells when no NoData matched them | One rule `valid_mask()` = not NoData-masked AND finite, used by R0 (valid cells, class values) and R1 (AOI valid share). New WARNING `RASTER_NONFINITE`; an all-non-finite raster is a FAIL. NaN declared as NoData is treated as NoData (masked), infinities remain non-finite | `TestV11NonFinite` (7): NaN, +inf, -inf, with NoData = none / -9999 / NaN; R0 and R1 agree with an independent count; all-non-finite; clean raster has no finding; readiness blocked by low valid share |
| 2 | Only the `.shp` was hashed | `dataset_files()`/`dataset_hashes()`: Shapefile companions (.shx .dbf .prj .cpg .sbn .sbx .qix .fix .atx .ixs .mxs .qpj .shp.xml) and GeoTIFF sidecars (.aux.xml .ovr .msk .tfw .wld) are hashed before and after intake (`INTEGRITY` FAIL names the changed file) and by the CLI preflight and the final post-output check (manifest lists every file). A Shapefile missing .shx or .dbf is a FAIL (`SHAPEFILE_PARTS`). Unrelated files that merely share a prefix are excluded | `TestV11Shapefile` (5) and `TestV11Main` (CLI): tampering with .dbf/.shx/.prj/.cpg/.shp during intake, and with .dbf after intake before the final check (rc 3) |
| 3 | `2021-11-05garbage` was accepted (`[:10]` slice) | `parse_iso_date()`: ONLY `YYYY-MM-DD` (ASCII digits, zero-padded, real calendar day, nothing before/after; a `date` object is accepted, a `datetime` is not). Time of day belongs in `obs_time_of_day`. Same strictness for scene dates, event windows and `--today` (CLI stops with rc 2 before writing) | `TestV11Dates` (4) plus CLI test: 24 negative and 4 positive forms |
| 4 | R2 ignored CRS / resolution / origin mismatches | Policy below | `TestV11AlignmentPolicy` (7) plus CLI default-vs-strict test |

### R2 alignment policy (chosen, documented in `RI.ALIGNMENT_POLICY` and in every report)
For a RASTER reference, a CRS, resolution or cell-origin mismatch with the Sentinel-1 analysis grid, or a rotated transform, means a cell-wise comparison would first need resampling/reprojection of the reference data. That is a methodological choice that can change results, so it must not pass silently, and it should not be decided by software.
- **Default:** the mismatch does NOT change any existing eligibility threshold (`RI.DEFAULTS` is asserted unchanged by a test). It is listed under `alignment_conditions`, the verdict text becomes "... ONLY WITH AN EXPLICIT TEAM DECISION ON ALIGNMENT", `team_decision_required` = `["alignment"]`, and the Markdown report prints "TEAM DECISION REQUIRED: alignment".
- **Strict (`--strict-alignment` / `strict_alignment=True`):** each condition becomes a candidate-label BLOCKER.
- Real blockers always take precedence: conditions never make a NOT READY verdict look eligible.
- **Vector/point references:** a CRS difference is routine geometry reprojection (no data resampling) and is only recorded as evidence, not as a condition.
- Presence-only and qualitative verdicts are unaffected (tested). Nothing performs any resampling or reprojection.

## What exists (all new files; nothing in the existing project is modified)
| File | Purpose |
|---|---|
| `src/flood_detection/ref_integration.py` | R0 `intake()`, R1 `alignment()`/`temporal()`, R2 `readiness()` (pure library, read-only on references) |
| `scripts/reference_integration_check.py` | CLI for one reference + sidecar; writes 7 files to a NEW directory |
| `tests/test_ref_integration.py` | 63 tests, synthetic fixtures only |
| `docs/reference_meta_template.json` | sidecar template, every value UNCONFIRMED |
| `docs/reference_integration_R0_R2_report.md` | this report |

## Supported reference formats
GeoTIFF raster (`extent_raster`); GeoJSON / GPKG / Shapefile (all companion files hashed) polygons (`extent_polygons`) or points (`points`, `depth_points`); CSV points (needs `declared_crs`, optional `x_column`/`y_column`). Anything else (PDF, JPEG, map service) is a FAIL for format and is qualitative-only until georeferenced. Metadata comes from a JSON sidecar whose statements (producer, licence, independence, method) are recorded but NOT verified.

## R0 intake (PASS / WARNING / FAIL per finding)
File presence, non-empty, readable, SHA-256 before/after; format; metadata fields present and not UNCONFIRMED; kind vs actual content; CRS (embedded, declared-only = WARNING, invalid / missing / disagreeing = FAIL); raster NoData, valid cells, rotation, class values vs `class_meaning`; vector geometry (null/empty/invalid, mixed types, zero-area polygons, duplicate points, longitude/latitude range); dates (missing, non-ISO, future, reversed, wide range, no time of day); AOI footprint coverage; licence, independence, method and positional-accuracy fields.

## R1 alignment
CRS vs analysis CRS (EPSG:32644), resolution relation to 30 m (equal / finer or coarser, integer or not), cell-origin offset, valid-data share of the reference's OWN cells inside the AOI, features inside the AOI, signed day offsets to each of the eight 2021 Sentinel-1 dates, overlap/gap against intended event windows (config `2021_sep_nov` window, labelled PROPOSED, plus any `--event-window`). Mismatches are reported only: no reference data are reprojected, resampled or edited; the AOI geometry is transformed only to measure overlap. Day thresholds (3 d close, 6 d half-revisit) are analyst conventions.

## R2 readiness
Three independent verdicts, each with blockers and evidence: candidate-label comparison, presence-only comparison, qualitative comparison; primary class = highest eligible, else `UNUSABLE`. The strongest possible outcome is "ELIGIBLE FOR TEAM REVIEW"; `authoritative_reference` is always "NOT ASSESSED BY SOFTWARE". A Sentinel-1-derived or independence-unknown reference cannot be eligible for candidate-label comparison. Reported locations are presence-only (absence of a report is not absence of flooding).

## Safeguards
Every source (reference, sidecar, configuration, AOI GeoJSON files, settings, optional meta, rainfall_events.json) is hashed BEFORE it is parsed or loaded and again after all outputs; outputs go to a new directory (default `outputs/flood_reference_readiness/<ref stem>/`), never overwrite, refuse `outputs`, `outputs/reports|tables|figures|maps`, `outputs/chirps_2021`, `outputs/s1_2021_persistence*` and the reference's own folder (nested or ancestor); `status.json` is never written; no network, Earth Engine, ASF or Copernicus.

## Known limitations
- No real reference file exists in the project; everything is tested on synthetic fixtures. Behaviour on real products (multi-band rasters, multi-layer GPKG, odd class schemes) is UNTESTED.
- Only band 1 of a raster is examined (other bands are not validated); multi-layer vector files read the default layer.
- Footprint coverage uses bounding boxes, not the mapped area; a raster's valid share is the real data check.
- Swapped longitude/latitude that stay inside valid ranges cannot be detected.
- Sidecar claims are not verified; the thresholds are conventions; time-of-day offsets are not assessed.
- Large rasters are read fully into memory.

## Installation (PowerShell, repo root; extract the ZIP over the repo - new files only)
```powershell
Expand-Archive -Path .\flood-reference-R0-R2-v1.2.zip -DestinationPath . -Force
.\.venv\Scripts\python -m pytest tests\test_ref_integration.py -q
.\.venv\Scripts\python -m pytest -q
# usage on a real file once the team has one (copy docs\reference_meta_template.json and fill it from the actual file):
.\.venv\Scripts\python scripts\reference_integration_check.py --reference <path-to-file> --meta <path-to-sidecar.json>
git status --short
```
The v1.2 ZIP replaces the five untracked v1/v1.1 files (same paths) and adds nothing else tracked; `-Force` overwrites only those untracked files. `SHA256SUMS.txt` is extracted to the repo root: compare, then delete it. Do not stage or commit until reviewed.

- v1.1 limitation: sidecar discovery for GeoTIFF/Shapefile is by file name; companions with unusual names or datasets split across folders are not detected. The alignment policy default is a documentation/decision gate, not a measured quality threshold.
