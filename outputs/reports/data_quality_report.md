# Data quality report

Grid: EPSG:32644, 30 m, 1416 x 726 cells

| feature | present | aligned | valid % | min | max |
|---|---|---|---|---|---|
| elevation_m | True | True | 100.0 | -16.819625854492188 | 53.76460647583008 |
| slope_deg | True | True | 100.0 | 0.0 | 33.312904357910156 |
| landcover_class | False | - | - | - | - |
| builtup_fraction | False | - | - | - | - |
| rain_event_total_mm | False | - | - | - | - |

## Missing features

- **flow_accumulation**: needs hydrologically conditioned DEM (e.g. pysheds/WhiteboxTools) - planned next
- **twi**: derived from flow accumulation + slope - planned next
- **distance_to_drainage**: needs OSM waterways/drains via Overpass - planned next
- **drainage_density**: needs OSM waterways - planned next
- **distance_to_roads**: needs OSM roads - planned next
- **population**: needs WorldPop/Census ward population - not yet acquired
- **relief_shelters**: needs shelter locations (OSM / GCC list) - not yet acquired
- **flood_labels**: needs Sentinel-1 flood extents (Module F, requires Google Earth Engine authentication)