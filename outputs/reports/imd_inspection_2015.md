# IMD rainfall inspection and conversion - 2015

**Native 0.25 deg conversion only: no resampling, no zero-filling. Demonstration version; day definition PROVISIONAL; not validated.**

- Raw file: `data/external/rainfall/imd_gridded_daily/raw/imd_rain_0p25_2015.nc` (preserved, read-only here); manifest: `imd_rain_0p25_2015.nc.manifest.json`; sha256 `c276ce7ebff1d74d79123a7c777d9ef61c3c5765aa3b6db464ff6224b30a3926`

- Format: NetCDF read with netCDF4
- Global attributes: {"history": "FERRET V6.82   20-Feb-26", "Conventions": "CF-1.0"}
- variable `LONGITUDE` dims=('LONGITUDE',) shape=(135,) dtype=float64 attrs={"units": "degrees_east", "point_spacing": "even", "axis": "X", "modulo": "360.0", "standard_name": "longitude"}
- variable `LATITUDE` dims=('LATITUDE',) shape=(129,) dtype=float64 attrs={"units": "degrees_north", "point_spacing": "even", "axis": "Y", "standard_name": "latitude"}
- variable `TIME` dims=('TIME',) shape=(365,) dtype=float64 attrs={"units": "days since 1900-12-31 00:00:00", "axis": "T", "time_origin": "31-DEC-1900", "standard_name": "time"}
- variable `RAINFALL` dims=('TIME', 'LATITUDE', 'LONGITUDE') shape=(365, 129, 135) dtype=float32 attrs={"missing_value": "-999.0", "_FillValue": "-999.0", "long_name": "Rainfall", "units": "mm", "history": "From ind2015_rfp25.grd"}
- Rain variable `RAINFALL`, axes (time,lat,lon) = dims ('TIME', 'LATITUDE', 'LONGITUDE'); time `TIME`, lat `LATITUDE`, lon `LONGITUDE`
- Values flagged missing by attributes/UNDEF: 4544615
- Grid: 129 x 135, lat 6.5..38.5 (ascending, flipped to north-up), lon 66.5..100.0, spacing 0.25 deg
- Registration: coordinates treated as cell centres (PROVISIONAL: IMD says 'grid points'; transform origin 66.375, 38.625)
- Time: 365 daily records 2015-01-01..2015-12-31 (NetCDF `TIME` units 'days since 1900-12-31 00:00:00'); continuous: yes
- Units: mm (NetCDF attribute)
- Study-area bounds (np.float64(80.1339), np.float64(12.852), np.float64(80.3329), np.float64(13.2352)) overlap 3 native cell(s): [r101 c55 centre 80.250E 13.250N]; [r102 c55 centre 80.250E 13.000N]; [r103 c55 centre 80.250E 12.750N]
  cell r101 c55: 0 of 365 days NaN (all-year), min 0.0, max 329.34344482421875
  cell r102 c55: 365 of 365 days NaN (all-year), min n/a, max n/a
  cell r103 c55: 365 of 365 days NaN (all-year), min n/a, max n/a

## Conversion
- Dates written: 2015-07-21..2015-12-20 (153 files) to `data/external/rainfall/imd_gridded_daily/daily`; GeoTIFF float32, EPSG:4326, nodata -9999.0, native 0.25 deg transform.
- NaN (missing/undefined) cell-days kept as nodata: 1905003; negative values: 0; > 1000 mm: 0 (flagged, not altered here; the workflow excludes them as invalid).
- Read-back checks: 2015-07-21 cell r101 c55: cube 0.0 vs GeoTIFF 0.0 -> match; 2015-07-21 cell r102 c55: cube nan vs GeoTIFF -9999.0 -> match; 2015-07-21 cell r103 c55: cube nan vs GeoTIFF -9999.0 -> match; 2015-10-05 cell r101 c55: cube 0.10526443272829056 vs GeoTIFF 0.10526443272829056 -> match; 2015-10-05 cell r102 c55: cube nan vs GeoTIFF -9999.0 -> match; 2015-10-05 cell r103 c55: cube nan vs GeoTIFF -9999.0 -> match

## Day definition (provisional)
PROVISIONAL (unverified for this product): 24-h accumulation ending 08:30 IST on the labelled date; the labelling convention (end date vs start date) is not confirmed.
For a Sentinel-1 pass at ~06:01 IST on date D, the daily value labelled D (if it ends 08:30 IST on D) includes ~21.5 h BEFORE the pass and ~2.5 h after it; excluding it (as the workflow does) gives a completed-day antecedent estimate that ends 08:30 IST on D-1 and misses the last ~21.5 h before the pass. It is not an exact pre-pass 24-h total.

Unresolved: day-label convention, grid-point registration (centre assumed), licence, and whether IMD's 'undefined' cells cover part of the Chennai coast.