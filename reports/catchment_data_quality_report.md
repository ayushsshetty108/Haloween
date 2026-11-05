# FLOODCAST catchment data quality report

Retrieval/processing date: 2026-11-05.

## First-version status

The output has 4 rows, one per requested USGS station, and exactly the required 18 columns. Original raw project files were preserved. Missing values remain blank; no substitute estimates were inserted.

## Boundary validation and drainage areas

The selected spatial boundary is the exact-gage split NLDI/NHDPlus upstream basin: `(full upstream basin − full local COMID catchment) ∪ upstream split at the verified NWIS station coordinate`. Station ID, NLDI identifier, COMID, reach measure and coordinates were matched exactly; the local split and full basin were geometry-checked. The 07010000 source polygon required Shapely `make_valid` repair. Boundary areas were computed geodesically and compared with the same NHDPlus flowline `TotDASqKm`.

NHDPlus and the split NLDI polygon agree within 0.1% for all stations, but the disagreement with NWIS total drainage area is unresolved for 07010000 and 08158000. The output retains NWIS areas as the reported total/contributing fields and does not substitute polygon area. See `catchment_boundary_validation.md` for exact deltas and unusable StreamStats records.

| Station | NWIS total (sq mi) | NWIS contributing (sq mi) | NHDPlus TotDA (sq mi) | Selected split polygon (sq mi) | Polygon vs NWIS | Decision |
|---|---:|---:|---:|---:|---:|---|
| 01646500 | 11560 | blank | 11562.64 | 11561.75 | 0.015% | ACCEPTED |
| 02087500 | 1150 | blank | 1153.76 | 1153.44 | 0.299% | ACCEPTED |
| 07010000 | 697000 | blank | 667324.34 | 667297.09 | -4.262% | ACCEPTED; NWIS AREA DISCREPANCY FLAGGED |
| 08158000 | 39009 | 27606.0 | 34710.30 | 34708.05 | -11.026% | ACCEPTED; NWIS AREA DISCREPANCY FLAGGED |

## Collected metrics

### 3DEP elevation and slope

USGS 3DEP ImageServer statistics were requested with 30 m output pixels in EPSG:5070, in 150 km tiles. Elevation tile means are combined using each tile's equal-area basin-intersection area; basin minima/maxima are the extrema of tile statistics. The source service is a dynamic multiresolution mosaic (its underlying source DEM resolution can vary).

Slope was requested from the same service using its Slope raster function with `ZFactor=1`, percent-rise mode and edge-effect removal. Returned percent-rise statistics contained extreme values (raw means over 1,000% and maxima above 2,000,000% in the completed small basins), so `mean_slope_pct` is intentionally left blank. These results are not used as terrain slope; a manual 30 m DEM download and local Horn 3×3 slope calculation with edge/nodata screening is required if the service continues to return those artifacts.

Minimum elevation can include below-sea-level values in mapped water/bathymetric cells; this is a 3DEP surface minimum and is not a land-only elevation minimum.

### Annual NLCD

All four station results are from the USGS Annual NLCD image services at 30 m for 2024, the latest year exposed in the queried service time extent. Forest is classes 41/42/43; developed/urban is classes 21/22/23/24; impervious cover is the average fractional-impervious pixel value. The incomplete first attempts for 02087500 and 07010000 were preserved; their complete retry files were selected. No further NLCD requests were made after successful retry completion.

### PRISM precipitation

The project downloaded the official PRISM 1991–2020 4 km annual precipitation BIL ZIP (precipitation normals version M3, dataset type `an81/r2103h`). Each grid cell was intersected with the basin in EPSG:5070 and weighted by the exact clipped cell area. All four area-weighted basin outputs are present. They differ slightly from the cached EPA StreamCat `precip9120ws` values because this calculation uses the gage-split boundary and PRISM grid directly.

## Missing values

- `contributing_drainage_area_sq_mi`: blank for 3/4 stations.
- `mean_elevation_m`: blank for 2/4 stations.
- `minimum_elevation_m`: blank for 2/4 stations.
- `maximum_elevation_m`: blank for 2/4 stations.
- `mean_slope_pct`: blank for 4/4 stations.
- `wetland_cover_pct`: blank for 4/4 stations.
- `soil_group_a_pct`: blank for 4/4 stations.
- `soil_group_b_pct`: blank for 4/4 stations.
- `soil_group_c_pct`: blank for 4/4 stations.
- `soil_group_d_pct`: blank for 4/4 stations.
- `available_water_capacity`: blank for 4/4 stations.
- `saturated_hydraulic_conductivity`: blank for 4/4 stations.

### Soil (SSURGO)

No basin-wide SSURGO mapunit/component/horizon extraction completed in this time-optimized first pass; there were no cached SSURGO polygons or tabular attributes in `data/raw/`. A valid result requires clipping current SSURGO mapunit polygons to each accepted basin, weighting by clipped mapunit area and `comppct_r`, and joining hydrologic group plus horizon attributes. The required manual/local alternative is to download the SSURGO spatial and tabular packages for every soil survey area intersecting each watershed, or implement the NRCS Soil Data Access pAOI POST workflow and extract component and horizon tables. Dual groups A/D, B/D and C/D must remain explicit or be assigned under a documented drained/undrained scenario; none were guessed here.

### NWI wetlands

The USFWS NWI Feature Layer was reachable. A Neuse-basin request returned 500-feature pages; it had delivered 14,500 polygons and was still paging when work was stopped to prioritize 3DEP. Partial compressed raw pages are retained under `data/raw/nwi_pages/`, but they do not cover a complete station result and were not used. The official layer schema exposes wetland type and QA/QC code but no feature mapping-date field. To complete this feature efficiently, obtain the USFWS NWI state/watershed bulk downloads covering the full basin extents, retain their metadata, mosaic locally and clip the wetlands-only Cowardin classes to each validated basin.

## Missing-field details by station

- **01646500:** mean_slope_pct: 3DEP percent-rise output failed quality screening (incomplete tiles or implausible extreme values; no slope statistic published); wetland_cover_pct: NWI feature pagination/clip was not completed for all basin features; partial raw pages are not used.
- **02087500:** mean_slope_pct: 3DEP percent-rise output failed quality screening (incomplete tiles or implausible extreme values; no slope statistic published); wetland_cover_pct: NWI feature pagination/clip was not completed for all basin features; partial raw pages are not used.
- **07010000:** mean/minimum/maximum elevation: completed 3DEP basin-tile result not available; mean_slope_pct: completed 3DEP basin-tile result not available; wetland_cover_pct: NWI feature pagination/clip was not completed for all basin features; partial raw pages are not used.
- **08158000:** mean/minimum/maximum elevation: completed 3DEP basin-tile result not available; mean_slope_pct: completed 3DEP basin-tile result not available; wetland_cover_pct: NWI feature pagination/clip was not completed for all basin features; partial raw pages are not used.

## Validation checks

- Four unique station IDs and the required CSV column order were checked after writing and reloading with pandas.
- Drainage areas are read from the preserved USGS project source and checked in the boundary validation report against NWIS records.
- Land-cover percentages are checked to lie in 0–100; precipitation/elevation values are not silently rounded into estimates.
- Blank fields indicate a missing or rejected source result, not zero.

## Source URLs and versions

- USGS NLDI basin and split process: https://api.water.usgs.gov/docs/nldi/basin/ and https://api.water.usgs.gov/docs/nldi-pygeoapi/splitcatchment/.
- USGS NHDPlus/Hydrologic Geospatial Fabric: https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items.
- USGS 3DEP service: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer (dynamic source mosaic; 30 m output request; retrieval date recorded in raw tile responses).
- USGS Annual NLCD Collection 1.2 (2024 service slice; 30 m): https://www.usgs.gov/centers/eros/science/about-annual-nlcd and https://doi.org/10.5066/P94UXNTS.
- PRISM 1991–2020 precipitation normals, 4 km M3: https://prism.oregonstate.edu/normals/ and https://prism.oregonstate.edu/request/normals/1991-2020_M3/4km/ppt/.
- USDA NRCS SSURGO and Soil Data Access: https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo and https://sdmdataaccess.nrcs.usda.gov/webservicehelp.aspx.
- USFWS NWI web services/data: https://www.fws.gov/program/national-wetlands-inventory/wetlands-data and https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest.

## Retained source files

All existing user-supplied discharge, NASA POWER, drainage-area and StreamStats files were left unchanged. New official source files are stored under `data/raw/`; prior/incomplete API responses are retained as audit artifacts rather than replaced.
