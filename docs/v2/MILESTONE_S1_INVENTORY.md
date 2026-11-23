# V2.3-dev milestone: Sentinel-1 inventory, baseline assessment, data readiness
Status of evidence: items marked (USER RUN) come from outputs the user reported from Windows; items marked (CODE) are from reading code; (UNTESTED) means no live run yet.

## A. Audit of `s1_window_scan.py` / `s1_window.py` (CODE + USER RUN)
1. All IW acquisitions intersecting the AOI queried? YES: `COPERNICUS/S1_GRD`, `filterBounds(AOI)`, `filterDate`, `instrumentMode == IW`. Not filtered on pass, orbit, platform, polarisation or product type. Other modes (EW/SM) are excluded by design; absence of other modes is NOT proven.
2. Ascending and descending included: YES (no pass filter). 3. Different relative orbits: YES. 4. Different platforms: YES.
5-6. `classify()` returns `COMPATIBLE` only if: mode IW; "VV" in polarisation list; coverage >= 95 %; valid >= 90 %; same pass; same relative orbit; same platform; (if the geometry otherwise matches) mean incidence angle within 1.0 deg of the reference. VH is NOT required (it is reported, not checked); product type/resolution (GRDH/GRDM), slice number and cycle are not checked. Different geometry takes precedence over unusable statistics.
7. Duplicates/slices: each Earth Engine image is one slice. If an AOI straddles two slices of one acquisition, each slice is classified alone and per-image coverage understates the date's coverage (possible false "unusable"); duplicates of the same id across windows are not an issue in one query. V2.3 `s1_inventory.py` de-duplicates ids across monthly windows, flags same date/orbit slice groups and computes a mosaic-based `date_group_valid_pct` for them.
8. Valid %: share of AOI pixels (30 m) whose VV mask is set; coverage %: footprint polygon vs AOI area (geodesic, max error 1 m); angle: AOI mean at 100 m. Different scales but each is consistent across images, so comparable between scenes. Footprint coverage includes no-data borders, so valid <= coverage is expected.
9. Sufficient for inventory? For the Nov 20-Dec 20 window, yes (3 items, all COMPATIBLE: 24 Nov, 6 Dec, 18 Dec; USER RUN). Not sufficient for a historical inventory (single window, no IST time, no slice handling, no candidate roles) -> `s1_inventory.py`.
Changes to the scan (justified, minimal): removed the unused `--any-orbit` option; removed the unused `all_iw` extra Earth Engine query (the window item count is reported instead); report now states the AOI provenance (provisional) and the exact query. No logic change to classification.

## B. Historical baseline inventory (`scripts/s1_inventory.py`, UNTESTED live)
Expected volume: Sentinel-1A only in 2014-15; roughly 2-4 IW items per 12 days over the AOI across geometries, i.e. tens of images for Oct 2014-Dec 2015 (estimate, not measured). Queried in monthly windows (15 calls), 3 retries each, results cached per window (restartable), stats computed server-side per image. Existing scan outputs are never overwritten (`s1_inventory_*` names).
Already verified live earlier (USER RUN, V2.1 check): the Aug 20, Sep 1, Oct 19, Oct 31 and Nov 12 scenes exist in Earth Engine with exact ids, S1A, DESCENDING, relative orbit 92. Their AOI coverage/valid/angle/IST have NOT been collected yet; the inventory run adds them.

## C. Baseline suitability (evidence available now)
- 20 Aug and 1 Sep: candidate dry references; NOT established dry (no rainfall/hydrology data obtained; CHIRPS download previously failed).
- 19 Oct, 31 Oct: sensitivity observations; V2.2 used them in the pre-event median, which is a methodology risk (they may follow wet spells) and must be tested by a with/without sensitivity run, not assumed.
- 12 Nov: first-wave flood observation, not a baseline. 24 Nov: uncertain. 6 Dec: post-peak (~5 days after ~1 Dec), not peak. 18 Dec: uncertain, not confirmed recovery.
- Only four pre-flood same-geometry scenes + three later ones are known: a robust seasonal baseline is NOT available.

## D. Independent-reference readiness (`scripts/reference_readiness.py`, config/reference_datasets.json)
Seven candidate references registered; all NOT YET OBTAINED; formats, CRS, extents and licences UNCONFIRMED (Agent 1). UNOSAT/IWMI November products are Sentinel-1-derived -> NOT SUITABLE FOR QUANTITATIVE VALIDATION of an S1 proxy. `check_ingest()` lists the technical requirements a delivered file must meet (georeferenced, CRS, date, extent, class meaning, method/independence, licence).

## E. Alternative-event readiness (CODE; no processing)
- Config: `2021_nov` and `2023_dec` exist only as date windows (no `scene_ids`, no `orbit`). `s1b_flood_extent.py` refuses events without pinned scenes, and the gate, run id and output directories are per event, so adding pinned entries cannot alter `2015_nov` outputs.
- Needed per new event: scene scan, pinned ids, live EE verification table (`s1_gee_check.py`), gate pass, event-specific parameters. `s1b_params` is currently GLOBAL (shared; `--set` overrides give new run ids) -> add per-event parameter blocks if thresholds ever differ (change deferred).
- `s1_window.classify` is conservative across platforms (S1A vs S1B = different geometry). As far as I know Sentinel-1B stopped operating in Dec 2021, so 2021 scenes may involve both A and B and 2023 only S1A; verify with the scan, do not assume. Orbit formula supports S1A/S1B only (enough for both events).
- `2015_dec` config windows (peak 2015-12-02, post 12-02/12-14) are stale versus the real scenes (6 and 18 Dec): update only after the decision, with approval.
- Reference data, rainfall, ward vintages and shelters for 2021/2023: not assessed.

## Decision (provisional until the user's inventory run): CONDITIONAL GO
Supports: three same-geometry (S1A, DESCENDING, rel. orbit 92) scenes at 100 % coverage/valid in the Nov 20-Dec 20 window (USER RUN); four earlier same-geometry scenes verified in Earth Engine.
Against: no dry baseline established; tiny archive; no independent reference obtained; AOI is a provisional OSM polygon; no live test of the S1B Earth Engine code.
Conditions before any December flood classification: (1) inventory run completed and consistent; (2) rainfall evidence for baseline dates obtained from real data; (3) >=1 independent reference obtained and passing `check_ingest`; (4) boundary status documented in every output; (5) `2015_dec` event pinned with approval; (6) small real S1B test succeeds. Flood claims stay "SAR-derived proxy" until validated.

## Change log (V2.3-dev)
Modified: `scripts/s1_window_scan.py`, `src/utils/status.py` (modules S1W, S1I, REF). Added: `scripts/s1_inventory.py`, `scripts/reference_readiness.py`, `src/flood_detection/s1_inventory.py`, `ref_readiness.py`, `config/s1_candidate_roles.json`, `config/reference_datasets.json`, `tests/test_s1_inventory.py` (8 tests), this file.
Tests (Linux sandbox): `python -m pytest -q tests` -> 74 passed, 1 skipped.
