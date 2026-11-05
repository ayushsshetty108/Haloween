# Catchment data sources

Retrieved 2026-11-05. Original responses are preserved in `data/raw/`.

## Collected

- USGS NWIS Site Service: https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=01646500,02087500,07010000,08158000,01646502&siteOutput=expanded&siteStatus=all
  - Local response: `data/raw/usgs_station_verification_nwis.rdb`; fields used include exact `site_no`, station name, decimal coordinates, `drain_area_va`, and `contrib_drain_area_va`.
  - 01646502 is the adjusted Potomac record used only as an identity comparison.
- Existing station areas: `data/raw/usgs_drainage_areas.csv`; preserved and checked against NWIS.
- USGS NLDI station features: https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{station_id}?f=json
  - Local response: `data/raw/usgs_nldi_station_{station_id}.geojson`; exact site feature gives COMID and reach measure.
- USGS NLDI basin: https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{station_id}/basin?f=json&simplified=false
  - Local response: `data/raw/usgs_nldi_basin_{station_id}.geojson`; full-vertex upstream NHDPlusV2 polygon. Default call does not split the local catchment at the gage measure.
  - A `splitCatchment=true` request was attempted but returned an upstream 502/400 error; no split polygon was accepted.
- USGS Hydrologic Geospatial Fabric: https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items?comid={COMID}&limit=1&f=json
  - Local response: `data/raw/usgs_nhdplus_flowline_{station_id}.geojson`; `TotDASqKm` converted to square miles for comparison. Channel slope is not used as terrain slope.
- EPA StreamCat metrics API: https://api.epa.gov/StreamCat/streams/metrics
  - Local response: `data/raw/epa_streamcat_watershed_metrics.json`; registry: `data/raw/epa_streamcat_variable_info.csv`.
  - Requested `Ws` watershed metrics by exact COMID. These are basin-level COMID summaries, not station-point samples. They may include a complete local catchment rather than a split-at-gage polygon.

## Metric versions and resolution

- Land-cover metrics use NLCD 2019 classes: imperviousness; deciduous, evergreen, and mixed forest; developed open/low/medium/high intensity; woody and herbaceous wetland. NLCD grid resolution is 30 m. Values are StreamCat watershed metrics.
- PRISM `precip9120` and `tmean9120` are 1991–2020 normals summarized at watershed level. Precipitation is mm/year and temperature °C. PRISM source grids are available at 800 m and 4 km, but the StreamCat registry does not report which grid spacing produced these aggregates.
- StreamCat soils `clay`, `sand`, `om`, `rckdep`, and `wtdep` are STATSGO-derived summaries, not SSURGO. Permeability was excluded because its unit metadata conflict.
- StreamCat `elevws` is mean elevation in metres. The registry does not expose original elevation raster cell spacing.

## Not collected

- 3DEP DEM: no raster download or basin extraction; slope and elevation extrema remain blank.
- USDA SSURGO: no exact-basin overlay; hydrologic soil group fractions and AWC remain blank.
- USFWS NWI: no polygon overlay; wetland cover is an NLCD proxy.
- StreamStats saved tests: `data/raw/streamstats_ssdelineate_{station_id}.json` and `data/raw/streamstats_08158000.json`. Three stations returned explicit not-snappable warnings and tiny-cell polygons, which were rejected.

## Recommended source plan for exact-basin metrics

| Feature | Preferred source and access | Coverage/version | Extraction method |
|---|---|---|---|
| Exact basin boundary | USGS NLDI basin endpoint with `splitCatchment=true`; retry or use StreamStats only after a station-specific snap succeeds | NHDPlusV2 CONUS network; station features return COMID and reach measure | Validate polygon identity and projected area against NWIS total and contributing areas before use |
| Mean/min/max elevation and mean terrain slope | USGS 3DEP seamless 1/3 arc-second DEM through The National Map | Full CONUS coverage; approximately 10 m north-south spacing, east-west spacing varies with latitude | Clip the same DEM product to accepted split basins; compute elevation summaries and area-weighted slope; record tiles, vertical datum, and spacing |
| Imperviousness and land cover | USGS Annual NLCD Collection 1.2 (2025), or use 2019 consistently for historical comparability | CONUS; 30 m annual land-cover record, 1985–2025 | Overlay class pixels on accepted basin; distinguish fractional impervious layer from land-cover class percentages |
| Hydrologic soil groups and available water capacity | USDA NRCS SSURGO through Web Soil Survey or Soil Data Access | CONUS survey areas at variable map scales; annual soil refresh | Intersect map units with basin; weight component properties by map-unit area and component percentage; retain dual hydrologic groups explicitly |
| Mean annual precipitation | PRISM 1991–2020 annual precipitation normals | CONUS; choose and record one grid resolution (4 km or 800 m) | Area-weight grid values within each exact basin; do not sample at station coordinates |
| Wetland percentage | USFWS National Wetlands Inventory data download or web services | Broad CONUS coverage; updates twice yearly, with local mapping-vintage differences | Intersect/union wetland polygons with accepted basin and compute area percentage; report map dates and coverage gaps |

## Official documentation

- USGS NLDI basin endpoint and `splitCatchment` behavior: https://api.water.usgs.gov/docs/nldi/basin/
- EPA StreamCat framework and metric definitions: https://www.epa.gov/national-aquatic-resource-surveys/streamcat-dataset and https://www.epa.gov/national-aquatic-resource-surveys/streamcat-metrics-and-definitions
- USGS Annual NLCD Collection 1.2 (2025), 30 m: https://www.usgs.gov/centers/eros/science/usgs-eros-archive-land-cover-annual-nlcd-collection-1-land-cover
- PRISM 1991–2020 normals and available resolutions: https://www.prism.oregonstate.edu/normals/
- USGS 3DEP DEM products and resolutions: https://www.usgs.gov/3d-elevation-program/about-3dep-products-services
- USDA SSURGO overview and access: https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo
- USFWS NWI data layer and access: https://www.fws.gov/program/national-wetlands-inventory/wetlands-data
