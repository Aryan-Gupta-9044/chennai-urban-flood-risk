# Sentinel-1 2021 date-level preprocessing report (M4C)

PREPROCESSING ONLY. No flood classification, no flood extent, no baseline designation (4 Nov 2021 is NOT a dry reference), no validation, no ML.

## Status

- **This run - dates requested (8): 2021-09-05, 2021-09-17, 2021-09-29, 2021-10-11, 2021-10-23, 2021-11-04, 2021-11-16, 2021-11-28.** QA_PASS for VV and VH: **8 of 8**. QA_PASS = technical checks only (grid, valid share, NoData, extremes, source-vs-output power, metadata).
- **Overall M4C - all 8 configured dates: 8 of 8 QA_PASS (VV and VH).** Overall status: **COMPLETE**.
- COMPLETE requires all configured dates to have both VV and VH QA_PASS with the current configuration signature; rows from an older configuration, failed, stale or not-yet-run dates do not count.
- Output grid: EPSG:32644, 30 m, shape [1416, 726], transform [30.0, 0.0, 406020.0, 0.0, -30.0, 1463310.0] (project master grid). AOI: PROVISIONAL - PROVISIONAL OSM boundary, not the official GCC boundary; fingerprint `129aada1a243`.
- Earth Engine run in this invocation: yes. Collection `COPERNICUS/S1_GRD`; configuration `config/s1_preprocess.json` (version M4C-1).
- Metadata JSON `status` is updated to the date's final QA state after QA (the earlier export state is kept as `export_status`); the QA CSV `date_status`, this report and the run state show the same state.

### Overall state by date

| date | state |
|---|---|
| 2021-09-05 | QA_PASS |
| 2021-09-17 | QA_PASS |
| 2021-09-29 | QA_PASS |
| 2021-10-11 | QA_PASS |
| 2021-10-23 | QA_PASS |
| 2021-11-04 | QA_PASS |
| 2021-11-16 | QA_PASS |
| 2021-11-28 | QA_PASS |

## Processing chain: what is done where

| step | applied by | notes |
|---|---|---|
| thermal noise removal | Earth Engine ingestion (catalog page) | not repeated |
| radiometric calibration (sigma0) | Earth Engine ingestion | not repeated |
| terrain correction | Earth Engine ingestion: SRTM 30 m (ASTER > 60 deg lat) | ellipsoid-based; DEM version per scene not exposed |
| dB conversion | Earth Engine ingestion | values are dB; this workflow converts to linear power only to average, then back |
| border-noise removal | NOT confirmed from the catalog page | checked empirically: edge/seam diagnostics + previews; no extra masking applied |
| radiometric terrain flattening | **not applied, not claimed** | slope/aspect effects remain in backscatter |
| incidence-angle normalisation | not applied | `angle` band is ~20 km pixels (approximate); documented, not used |
| geometric resampling | this workflow | slice -> UTM 10 m lattice aligned to the master grid, nearest neighbour (geometric only) |
| overlap rule | this workflow | linear-power mean of the slices valid at a pixel (order independent); one valid slice -> that slice; none -> NoData |
| 10 m -> 30 m | this workflow | exact 3x3 block mean of linear power, then dB (default `linear_area_mean`); this is spatial averaging (multilooking) and irreversible |
| additional speckle filter | none in the default | `point_db` and `linear_area_mean_focal_median` are compared only |
| NoData | explicit sentinel -9999 for dB; `validfrac` and `valid` rasters; never 0 | cell valid if >= 50 % of its source pixels are valid |
| native 10 m rasters | not exported (size) | native information kept as scene IDs, source 10 m statistics and diagnostics in the metadata JSON |

## QA table (see outputs/tables/s1_2021_preprocessing_qa.csv)

| date | pol | status | AOI valid % | NoData cells in AOI | extreme low / high | mean dB | power ratio out/source | overlap px | seam zone-rest dB | failures |
|---|---|---|---|---|---|---|---|---|---|---|
| 2021-09-05 | VH | QA_PASS | 99.9975 | 12 | 0 / 95 | -15.163 | 0.9999 | 0 | -0.1524 |  |
| 2021-09-05 | VV | QA_PASS | 99.9975 | 12 | 0 / 14292 | -5.3404 | 0.9998 | 0 | 0.1544 |  |
| 2021-09-17 | VH | QA_PASS | 99.995 | 24 | 0 / 87 | -15.3802 | 1.0 | 0 | 0.1305 |  |
| 2021-09-17 | VV | QA_PASS | 99.995 | 24 | 0 / 12174 | -5.7926 | 0.9999 | 0 | 0.6026 |  |
| 2021-09-29 | VH | QA_PASS | 100.0 | 0 | 0 / 94 | -15.4359 | 1.0 | 0 | -0.1735 |  |
| 2021-09-29 | VV | QA_PASS | 100.0 | 0 | 0 / 11437 | -5.8566 | 1.0 | 0 | 0.2472 |  |
| 2021-10-11 | VH | QA_PASS | 99.9957 | 21 | 0 / 99 | -14.8521 | 1.0 | 0 | 0.0126 |  |
| 2021-10-11 | VV | QA_PASS | 99.9957 | 21 | 0 / 16042 | -5.0302 | 1.0 | 0 | 0.2768 |  |
| 2021-10-23 | VH | QA_PASS | 100.0 | 0 | 0 / 98 | -15.0518 | 0.9999 | 0 | -0.0616 |  |
| 2021-10-23 | VV | QA_PASS | 100.0 | 0 | 0 / 12916 | -5.5002 | 0.9999 | 0 | 0.4203 |  |
| 2021-11-04 | VH | QA_PASS | 99.9977 | 11 | 0 / 143 | -13.6389 | 1.0 | 0 | -0.3731 |  |
| 2021-11-04 | VV | QA_PASS | 99.9977 | 11 | 0 / 43726 | -3.0125 | 0.9999 | 0 | -0.109 |  |
| 2021-11-16 | VH | QA_PASS | 100.0 | 0 | 0 / 112 | -14.3938 | 1.0 | 0 | -0.0454 |  |
| 2021-11-16 | VV | QA_PASS | 100.0 | 0 | 0 / 22343 | -4.4772 | 0.9998 | 0 | 0.0662 |  |
| 2021-11-28 | VH | QA_PASS | 99.9994 | 3 | 0 / 139 | -13.7156 | 0.9999 | 0 | -0.032 |  |
| 2021-11-28 | VV | QA_PASS | 99.9994 | 3 | 0 / 42996 | -3.1424 | 0.9999 | 0 | 0.2507 |  |

## 2021-11-16 (confirmed separately)

- VH: **QA_PASS**; AOI valid 100.0 %; overlap px 0; seam zone-minus-rest -0.0454 dB; no failures recorded
- VV: **QA_PASS**; AOI valid 100.0 %; overlap px 0; seam zone-minus-rest 0.0662 dB; no failures recorded

## Speckle / resampling option comparison (server-side AOI statistics at 30 m; NOT a ranking)

| date | pol | option | mean dB | local residual std dB (lower = smoother) |
|---|---|---|---|---|
| 2021-09-05 | VH | point_db | -15.5669 | 2.5817 |
| 2021-09-05 | VH | linear_area_mean | -15.1631 | 1.7465 |
| 2021-09-05 | VH | linear_area_mean_focal_median | -15.1847 | 0.9015 |
| 2021-09-05 | VV | point_db | -5.8862 | 3.1133 |
| 2021-09-05 | VV | linear_area_mean | -5.3405 | 2.3394 |
| 2021-09-05 | VV | linear_area_mean_focal_median | -5.4942 | 1.2924 |
| 2021-09-17 | VH | point_db | -15.7861 | 2.5933 |
| 2021-09-17 | VH | linear_area_mean | -15.3805 | 1.7509 |
| 2021-09-17 | VH | linear_area_mean_focal_median | -15.4002 | 0.9037 |
| 2021-09-17 | VV | point_db | -6.3341 | 3.0992 |
| 2021-09-17 | VV | linear_area_mean | -5.7928 | 2.3282 |
| 2021-09-17 | VV | linear_area_mean_focal_median | -5.9475 | 1.2856 |
| 2021-09-29 | VH | point_db | -15.8386 | 2.5844 |
| 2021-09-29 | VH | linear_area_mean | -15.4362 | 1.7473 |
| 2021-09-29 | VH | linear_area_mean_focal_median | -15.4535 | 0.9026 |
| 2021-09-29 | VV | point_db | -6.3986 | 3.093 |
| 2021-09-29 | VV | linear_area_mean | -5.8569 | 2.324 |
| 2021-09-29 | VV | linear_area_mean_focal_median | -6.0114 | 1.2795 |
| 2021-10-11 | VH | point_db | -15.2506 | 2.5623 |
| 2021-10-11 | VH | linear_area_mean | -14.8524 | 1.7401 |
| 2021-10-11 | VH | linear_area_mean_focal_median | -14.8736 | 0.9005 |
| 2021-10-11 | VV | point_db | -5.5797 | 3.1206 |
| 2021-10-11 | VV | linear_area_mean | -5.0304 | 2.3427 |
| 2021-10-11 | VV | linear_area_mean_focal_median | -5.1817 | 1.2961 |
| 2021-10-23 | VH | point_db | -15.452 | 2.5694 |
| 2021-10-23 | VH | linear_area_mean | -15.0519 | 1.7401 |
| 2021-10-23 | VH | linear_area_mean_focal_median | -15.0728 | 0.8972 |
| 2021-10-23 | VV | point_db | -6.0431 | 3.0997 |
| 2021-10-23 | VV | linear_area_mean | -5.5003 | 2.3285 |
| 2021-10-23 | VV | linear_area_mean_focal_median | -5.6567 | 1.2825 |
| 2021-11-04 | VH | point_db | -14.0357 | 2.562 |
| 2021-11-04 | VH | linear_area_mean | -13.6392 | 1.7561 |
| 2021-11-04 | VH | linear_area_mean_focal_median | -13.6641 | 0.9144 |
| 2021-11-04 | VV | point_db | -3.5784 | 3.1732 |
| 2021-11-04 | VV | linear_area_mean | -3.0127 | 2.3788 |
| 2021-11-04 | VV | linear_area_mean_focal_median | -3.1534 | 1.3467 |
| 2021-11-16 | VH | point_db | -14.8097 | 2.6199 |
| 2021-11-16 | VH | linear_area_mean | -14.3942 | 1.7869 |
| 2021-11-16 | VH | linear_area_mean_focal_median | -14.4141 | 0.9426 |
| 2021-11-16 | VV | point_db | -5.044 | 3.1706 |
| 2021-11-16 | VV | linear_area_mean | -4.4775 | 2.3826 |
| 2021-11-16 | VV | linear_area_mean_focal_median | -4.6228 | 1.3386 |
| 2021-11-28 | VH | point_db | -14.1333 | 2.646 |
| 2021-11-28 | VH | linear_area_mean | -13.7158 | 1.8206 |
| 2021-11-28 | VH | linear_area_mean_focal_median | -13.7408 | 0.9696 |
| 2021-11-28 | VV | point_db | -3.7319 | 3.2372 |
| 2021-11-28 | VV | linear_area_mean | -3.1427 | 2.4335 |
| 2021-11-28 | VV | linear_area_mean_focal_median | -3.2872 | 1.3849 |

**Default selection (rationale, not a measured optimum):** `linear_area_mean` is the least-processing way to move intensity to a coarser grid without aliasing or an extra filter. The focal median is an additional, irreversible smoothing and is not the default; `point_db` discards 8 of 9 source pixels. The comparison above shows how the options differ; it does not show which is more accurate for any later use.

## Run state

| date | state | signature | error |
|---|---|---|---|
| 2021-09-05 | QA_PASS | `4c6f3a4e4ca35c07` |  |
| 2021-09-17 | QA_PASS | `83125cb01d505e59` |  |
| 2021-09-29 | QA_PASS | `c1a8031fae5ba7f6` |  |
| 2021-10-11 | QA_PASS | `ecaf36d7a2ffe359` |  |
| 2021-10-23 | QA_PASS | `0d0be3e4e2874b12` |  |
| 2021-11-04 | QA_PASS | `aa8fe50c512c569f` |  |
| 2021-11-16 | QA_PASS | `3fe3950379f8fe35` |  |
| 2021-11-28 | QA_PASS | `86b053134758fa6d` |  |

## Limitations

- Backscatter is not terrain-flattened; steep or tilted surfaces and urban double-bounce affect values. The 30 m product does not carry 30 m of independent SAR information: it is an average of 10 m pixels.
- Seam diagnostics are descriptive (zone mean vs rest of AOI, slice difference in overlap). A difference may be real land cover; inspect the previews.
- Earth Engine steps were not executed by the developer of this module; only your run produces real products. Synthetic unit tests do not validate real-data behaviour.
