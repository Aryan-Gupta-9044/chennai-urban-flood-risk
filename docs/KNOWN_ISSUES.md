# Known issues and limitations
1. **run.ps1 was not executed** (no Windows/PowerShell in the build sandbox). Its logic is simple, but the first Windows run is its first test. The Python pipeline it calls (`scripts/run_pipeline.py`) was run on Linux.
2. **Real DEM, WorldCover and CHIRPS downloads were not tested** (hosts blocked in the build sandbox). URLs follow the providers' documented layouts; if one fails the module reports BLOCKED with the reason. Manual drop-in folders are the fallback.
3. **Google Earth Engine code (Sentinel-1 flood extent) was never executed.** Thresholds (-3 dB change, < -15 dB, slope <= 5 deg, JRC water mask) are common starting values, not validated for Chennai. Event dates and S1 windows in config are proposals.
4. OSM boundary is PROVISIONAL. If OSM is unreachable, the union of the ward polygons is used (also PROVISIONAL).
5. Ward file has 201 polygons: 200 numbered wards plus one unnumbered polygon; check against the official GCC list.
6. CHIRPS is ~5 km: rainfall is nearly uniform across Chennai and carries little spatial signal for the RF; it is dropped automatically when constant.
7. Copernicus GLO-30 is a surface model; urban flat-terrain accuracy is limited.
8. RF caveats: SAR labels are proxies; slope appears both in the SAR mask and as a feature (circularity); spatial-block CV is not independent-event validation; negatives are subsampled.
9. User-supplied label rasters must already be on the master grid (EPSG:32644, 30 m, bbox from the study area); regridding helper not yet provided.
10. Dashboard raster overlays are nearest-neighbour reprojections for display only.
