# Implementation status (V2 working copy). T = tested here, U = untested, S = tested only on SIMULATED data
| Item | Status | Notes |
|---|---|---|
| V1 modules 0, A1, A2, B-H, report (Linux sandbox) | T / S | Unit tests pass; offline run reports BLOCKED correctly; raster/feature/RF/dashboard code run on a SIMULATED fixture (not shipped). Ward download worked in the sandbox |
| V1 on Windows 11 (`run.ps1`) | T (by user) | User reports the V1 run completed successfully (report contents not yet reviewed by me) |
| Real DEM / WorldCover / CHIRPS / OSM downloads | **U** | Hosts were blocked in the sandbox |
| V2 fixes (4) | T | Unit tests (13 total pass) |
| S1 pairing logic (`pair_scenes`, `normalise`) | T | On hand-made scene lists (logic only) |
| ASF live search (`search_asf`) | T (by user, V2.0) | Ran on Windows; returned 5 full-coverage Nov 2015 scenes. V2.1 orbit handling not yet re-run live |
| `s1_availability.py` offline path | T | Reports BLOCKED with reason |
| Earth Engine flood extent (`gee_s1_flood.py`, `s1_flood_extent.py` GEE path) | **U** | Never executed; needs authentication; thresholds unvalidated for Chennai |
| `s1_flood_extent.py --local` path | U | Uses V1's unit-tested change-detection function, but the script itself is not run |
| Agreement metrics | T | Tiny arrays |
| ML module (RF/XGBoost/SHAP, event validation) | not built | Design only |
| Dashboard D1-D5 | not built | V1 dashboard unchanged |
| Orbit extraction / derivation (`s1_orbits.py`) | T / S | 16 unit tests; ESA formula; end-to-end with a STUBBED (simulated) ASF response in the sandbox. Derived value 92 vs user's 164: unresolved until Earth Engine check |
| `s1_gee_check.py` | **U** (offline path T) | Offline path verified (writes NOT QUERIED report + commands). Live Earth Engine query never run; matching logic tested on hand-made items |

## V2.2 S1B status
| Part | State |
|---|---|
| Event config, gate, parameters, run id | TESTED (unit, Linux) |
| Tile plan / alignment, assembly checks, 10->30 m aggregation, statistics, report writer | TESTED on SYNTHETIC arrays (logic only) |
| CLI plan-only and gate-block paths | TESTED with a SYNTHETIC study area and the reported EE table values |
| Earth Engine layer graph, live re-check, tile download, Drive export | NOT TESTED (needs your Windows run) |
| Real flood-proxy output, map, processing report | NOT PRODUCED yet |
| Validation / accuracy | NONE - not claimed |

## V2.3 HYD status
| Part | State |
|---|---|
| Algorithms (conditioning, D8, accumulation conservation/brute-force check, thresholds, TWI guard, validation) | TESTED on SYNTHETIC rasters (Linux) |
| CLI end-to-end incl. metadata/alignment/reproducibility/refusal paths | TESTED on SYNTHETIC rasters; speed check 804k valid cells in ~6 s |
| Run on the real Chennai DEM | NOT RUN yet (needs your Windows run) |
| Hydrological validation | NONE - terrain-derived, unverified |

- IMD demo: code + synthetic tests DONE (125 passed, 1 skipped); real acquisition NOT RUN; real conversion/workflow outputs NOT PRODUCED.
