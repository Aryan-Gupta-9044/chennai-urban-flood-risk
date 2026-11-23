# Dataset inventory (planned sources; the live table is outputs/tables/dataset_inventory.csv)
| Dataset | Source | Status in this package |
|---|---|---|
| Study-area boundary | OSM Nominatim via osmnx | PROVISIONAL - verify against official GCC boundary |
| Ward boundaries | DataMeet Municipal_Spatial_Data (GitHub) | Downloaded in build sandbox; vintage/licence to be verified |
| DEM | Copernicus GLO-30 (AWS Open Data) | Not downloaded in build sandbox (network blocked) |
| Land cover | ESA WorldCover 2021 v200 (AWS Open Data) | Not downloaded in build sandbox |
| Rainfall | CHIRPS v2.0 daily p05, 2023-11-28..12-08 | Not downloaded in build sandbox |
| Sentinel-1 | Google Earth Engine COPERNICUS/S1_GRD | Needs authentication; not executed |
| OSM drainage/roads/shelters, population | OSM / WorldPop | Not yet acquired (next stage) |
