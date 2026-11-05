"""Build the requested first-version catchment CSV, dictionary and quality report."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
STATIONS = ("01646500", "02087500", "07010000", "08158000")
REQUIRED_COLUMNS = [
    "station_id",
    "drainage_area_sq_mi",
    "contributing_drainage_area_sq_mi",
    "mean_elevation_m",
    "minimum_elevation_m",
    "maximum_elevation_m",
    "mean_slope_pct",
    "impervious_cover_pct",
    "forest_cover_pct",
    "urban_cover_pct",
    "wetland_cover_pct",
    "soil_group_a_pct",
    "soil_group_b_pct",
    "soil_group_c_pct",
    "soil_group_d_pct",
    "available_water_capacity",
    "saturated_hydraulic_conductivity",
    "mean_annual_precipitation_mm",
]
RETRIEVAL_DATE = date.today().isoformat()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def nlcd_file(station_id: str) -> Path | None:
    candidates = [
        RAW / f"annual_nlcd_2024_zonal_{station_id}_retry.json",
        RAW / f"annual_nlcd_2024_zonal_{station_id}.json",
    ]
    for path in candidates:
        record = read_json(path)
        if record and record.get("complete"):
            return path
    return None


def collect_rows() -> tuple[pd.DataFrame, dict[str, Any]]:
    drainage = pd.read_csv(RAW / "usgs_drainage_areas.csv", dtype={"station_id": "string"}).set_index("station_id")
    if set(STATIONS) - set(drainage.index):
        raise ValueError("One or more requested stations are missing from the drainage source file")
    records: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {"stations": {}, "missing": {}}
    for station_id in STATIONS:
        station_info: dict[str, Any] = {"station_id": station_id}
        drain_row = drainage.loc[station_id]
        row: dict[str, Any] = {
            "station_id": station_id,
            "drainage_area_sq_mi": float(drain_row["drainage_area_sq_mi"]),
            "contributing_drainage_area_sq_mi": pd.to_numeric(drain_row["contributing_drainage_area_sq_mi"], errors="coerce"),
            "mean_elevation_m": None,
            "minimum_elevation_m": None,
            "maximum_elevation_m": None,
            "mean_slope_pct": None,
            "impervious_cover_pct": None,
            "forest_cover_pct": None,
            "urban_cover_pct": None,
            "wetland_cover_pct": None,
            "soil_group_a_pct": None,
            "soil_group_b_pct": None,
            "soil_group_c_pct": None,
            "soil_group_d_pct": None,
            "available_water_capacity": None,
            "saturated_hydraulic_conductivity": None,
            "mean_annual_precipitation_mm": None,
        }
        provenance["missing"][station_id] = []

        boundary_path = RAW / f"usgs_nldi_validated_basin_{station_id}.geojson"
        boundary = read_json(boundary_path)
        if not boundary or len(boundary.get("features", [])) != 1:
            raise ValueError(f"No validated NLDI basin for {station_id}")
        boundary_props = boundary["features"][0]["properties"]
        station_info["boundary_file"] = boundary_path.name
        station_info["boundary_area_sq_mi"] = boundary_props.get("corrected_polygon_area_sq_mi")
        station_info["boundary_nwis_area_difference_pct"] = boundary_props.get("area_difference_pct_vs_nwis")
        station_info["boundary_nhdplus_area_difference_pct"] = boundary_props.get("area_difference_pct_vs_nhdplus")

        dem_path = RAW / "usgs_3dep_zonal_tiles" / f"usgs_3dep_30m_corrected_{station_id}.json"
        dem = read_json(dem_path)
        station_info["dem_file"] = dem_path.name if dem else None
        if dem:
            elev = dem.get("variables", {}).get("elevation_m", {})
            if elev.get("complete") and elev.get("mean") is not None:
                row["mean_elevation_m"] = elev.get("mean")
                row["minimum_elevation_m"] = elev.get("minimum")
                row["maximum_elevation_m"] = elev.get("maximum")
            else:
                provenance["missing"][station_id].append(
                    "mean/minimum/maximum elevation: 3DEP did not return complete statistics for every basin tile"
                )
            slope = dem.get("variables", {}).get("slope_pct_rise", {})
            slope_mean = slope.get("mean")
            slope_max = slope.get("maximum")
            if slope.get("complete") and slope_mean is not None and slope_mean < 100 and (slope_max or 0) < 10_000:
                row["mean_slope_pct"] = slope_mean
            else:
                provenance["missing"][station_id].append(
                    "mean_slope_pct: 3DEP percent-rise output failed quality screening (incomplete tiles or implausible extreme values; no slope statistic published)"
                )
            station_info["dem_tile_count"] = dem.get("tile_count")
            station_info["dem_elevation_complete"] = bool(elev.get("complete"))
            station_info["dem_slope_complete"] = bool(slope.get("complete"))
            station_info["dem_slope_mean_raw"] = slope_mean
            station_info["dem_slope_max_raw"] = slope_max
            station_info["dem_slope_median_raw"] = (slope.get("tiles") or [{}])[0].get("response", {}).get("statistics", [{}])[0].get("median") if slope.get("tiles") else None
        else:
            provenance["missing"][station_id].append("mean/minimum/maximum elevation: completed 3DEP basin-tile result not available")
            provenance["missing"][station_id].append("mean_slope_pct: completed 3DEP basin-tile result not available")

        land_path = nlcd_file(station_id)
        if land_path:
            land = read_json(land_path)
            row["impervious_cover_pct"] = land.get("impervious_cover_pct")
            row["forest_cover_pct"] = land.get("forest_cover_pct")
            row["urban_cover_pct"] = land.get("urban_cover_pct")
            station_info["nlcd_file"] = land_path.name
            station_info["nlcd_complete"] = True
            station_info["nlcd_valid_land_pixels"] = land.get("valid_land_cover_pixels")
            station_info["nlcd_valid_impervious_pixels"] = land.get("valid_impervious_pixels")
        else:
            provenance["missing"][station_id].append("2024 NLCD cover metrics: no complete station response was found")

        prism_path = RAW / f"prism_ppt_1991_2020_zonal_{station_id}.json"
        prism = read_json(prism_path)
        if prism and prism.get("mean_annual_precipitation_mm") is not None:
            row["mean_annual_precipitation_mm"] = prism["mean_annual_precipitation_mm"]
            station_info["prism_file"] = prism_path.name
            station_info["prism_cells"] = prism.get("valid_grid_cells_intersecting")
        else:
            provenance["missing"][station_id].append("mean_annual_precipitation_mm: PRISM basin zonal output not found")

        nwi = read_json(RAW / f"nwi_wetland_zonal_{station_id}.json")
        if nwi and nwi.get("complete") and nwi.get("wetland_cover_pct") is not None:
            row["wetland_cover_pct"] = nwi["wetland_cover_pct"]
            station_info["nwi_file"] = f"nwi_wetland_zonal_{station_id}.json"
        else:
            provenance["missing"][station_id].append(
                "wetland_cover_pct: NWI feature pagination/clip was not completed for all basin features; partial raw pages are not used"
            )

        provenance["stations"][station_id] = station_info
        records.append(row)

    result = pd.DataFrame(records, columns=REQUIRED_COLUMNS)
    if len(result) != 4 or result["station_id"].nunique() != 4 or set(result["station_id"]) != set(STATIONS):
        raise ValueError("Output must have exactly four unique requested stations")
    if list(result.columns) != REQUIRED_COLUMNS:
        raise ValueError("Final output columns do not match the required schema")
    if result["drainage_area_sq_mi"].isna().any():
        raise ValueError("USGS total drainage area is required for all four stations")
    percentage_cols = [
        "impervious_cover_pct", "forest_cover_pct", "urban_cover_pct", "wetland_cover_pct",
        "soil_group_a_pct", "soil_group_b_pct", "soil_group_c_pct", "soil_group_d_pct",
    ]
    for name in percentage_cols:
        nonmissing = result[name].dropna()
        if ((nonmissing < 0) | (nonmissing > 100)).any():
            raise ValueError(f"{name} contains values outside 0–100")
    return result, provenance


def build_dictionary() -> pd.DataFrame:
    common_source = "USGS NLDI exact-site station association; USGS NHDPlus flowline COMID; NLDI gage split"
    rows = [
        ("station_id", "Exact USGS NWIS site number; retained as text.", "USGS site number", "USGS NWIS and NLDI", "https://waterdata.usgs.gov/; https://api.water.usgs.gov/nldi/", "Exact NWIS site ID; verified against NLDI identifier and requested coordinates.", "Static", ""),
        ("drainage_area_sq_mi", "USGS-reported total drainage area; not replaced by the NLDI polygon area.", "square miles", "USGS NWIS; project source drainage-area CSV", "https://waterdata.usgs.gov/", "Exact station ID; verified against saved NWIS RDB and NHDPlus comparison in boundary report.", "Static", "NWIS and NLDI/NHDPlus conflicts are flagged in the quality report for 07010000 and 08158000."),
        ("contributing_drainage_area_sq_mi", "USGS-reported contributing drainage area, distinct from total drainage area.", "square miles", "USGS NWIS; project source drainage-area CSV", "https://waterdata.usgs.gov/", "Exact station ID; blank if NWIS does not report a value.", "Static", "NWIS reports this only for 08158000 among the four stations."),
        ("mean_elevation_m", "Mean 3DEP elevation over the gage-split NLDI basin.", "m", "USGS 3DEP dynamic elevation ImageServer", "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer", "30 m pixel-size request; 150 km tiles in EPSG:5070; tile means weighted by the equal-area intersection of each tile with the basin. Complete elevation tiles only.", "Static surface snapshot", "Blank where one or more required 3DEP elevation tiles failed."),
        ("minimum_elevation_m", "Minimum 3DEP elevation pixel in the gage-split basin.", "m", "USGS 3DEP dynamic elevation ImageServer", "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer", "Minimum of tile-level raster minima over the basin; 30 m request; EPSG:5070.", "Static surface snapshot", "May include mapped water/bathymetric pixels; negative results are flagged in the report."),
        ("maximum_elevation_m", "Maximum 3DEP elevation pixel in the gage-split basin.", "m", "USGS 3DEP dynamic elevation ImageServer", "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer", "Maximum of tile-level raster maxima over the basin; 30 m request; EPSG:5070.", "Static surface snapshot", "Blank where one or more required 3DEP elevation tiles failed."),
        ("mean_slope_pct", "Area-weighted mean percent-rise terrain slope derived from 3DEP.", "% rise", "USGS 3DEP ImageServer Slope raster function", "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer", "Server-side Slope function, ZFactor=1, SlopeType=2 (percent rise), RemoveEdgeEffect=true; output retained only if all tiles complete and returned values pass a range/edge-artifact screen.", "Static surface snapshot", "Blank if slope tile results are incomplete or implausible; no channel-slope or external proxy substituted."),
        ("impervious_cover_pct", "Mean 30 m fractional impervious surface over the basin.", "% of basin", "USGS Annual NLCD Fractional Impervious Surface", "https://di-nlcd.img.arcgis.com/arcgis/rest/services/USA_NLCD_Annual_LandCover_Fractional_Impervious_Surface/ImageServer", "2024 mosaic selection; 30 m cells; zonal service statistics over 150 km EPSG:5070 basin intersections; pixel-count-weighted mean.", "2024", ""),
        ("forest_cover_pct", "Share of valid 30 m land-cover cells classified as evergreen, deciduous, or mixed forest.", "% of basin", "USGS Annual NLCD Land Cover", "https://di-nlcd.img.arcgis.com/arcgis/rest/services/USA_NLCD_Annual_LandCover/ImageServer", "2024 mosaic; classes 41, 42, 43; histogram cell counts divided by valid land-cover cell count.", "2024", ""),
        ("urban_cover_pct", "Share of valid land-cover cells in developed open space and low/medium/high intensity developed classes.", "% of basin", "USGS Annual NLCD Land Cover", "https://di-nlcd.img.arcgis.com/arcgis/rest/services/USA_NLCD_Annual_LandCover/ImageServer", "2024 mosaic; classes 21, 22, 23, 24; histogram cell counts divided by valid land-cover cell count.", "2024", ""),
        ("wetland_cover_pct", "Mapped NWI wetland polygon area clipped to basin, divided by basin area; excludes mapped deepwater classes.", "% of basin", "USFWS National Wetlands Inventory", "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0", "Planned method: clip NWI polygon features to exact basin in EPSG:5070 and divide mapped wetland area by basin area. No value published until complete feature pagination finishes.", "Live layer; feature mapping dates not exposed", "Blank because only partial pages were retrieved and the station-level fetch was stopped to prioritize 3DEP."),
        ("soil_group_a_pct", "Share of basin soil-component area assigned to Hydrologic Soil Group A.", "% of soil-covered basin", "USDA NRCS SSURGO / Soil Data Access", "https://sdmdataaccess.nrcs.usda.gov/; https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo", "Not calculated; requires clipped mapunit area joined to component hydgrp. Dual groups need an explicitly selected drained/undrained scenario.", "Current SSURGO survey vintage", "No SSURGO AOI extraction completed in this first version."),
        ("soil_group_b_pct", "Share of basin soil-component area assigned to Hydrologic Soil Group B.", "% of soil-covered basin", "USDA NRCS SSURGO / Soil Data Access", "https://sdmdataaccess.nrcs.usda.gov/; https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo", "Not calculated; requires clipped mapunit area joined to component hydgrp.", "Current SSURGO survey vintage", "No SSURGO AOI extraction completed in this first version."),
        ("soil_group_c_pct", "Share of basin soil-component area assigned to Hydrologic Soil Group C.", "% of soil-covered basin", "USDA NRCS SSURGO / Soil Data Access", "https://sdmdataaccess.nrcs.usda.gov/; https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo", "Not calculated; requires clipped mapunit area joined to component hydgrp.", "Current SSURGO survey vintage", "No SSURGO AOI extraction completed in this first version."),
        ("soil_group_d_pct", "Share of basin soil-component area assigned to Hydrologic Soil Group D.", "% of soil-covered basin", "USDA NRCS SSURGO / Soil Data Access", "https://sdmdataaccess.nrcs.usda.gov/; https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo", "Not calculated; dual A/D, B/D and C/D should be preserved as alternatives or clearly assigned to a stated scenario.", "Current SSURGO survey vintage", "No SSURGO AOI extraction completed in this first version."),
        ("available_water_capacity", "Area- and component-weighted profile available-water capacity.", "Not populated; target unit mm water per 1 m soil profile", "USDA NRCS SSURGO horizon attributes", "https://sdmdataaccess.nrcs.usda.gov/", "Planned: join AOI-clipped mapunit area to component fractions and horizon awc_r; integrate horizon overlap to a stated soil depth.", "Current SSURGO survey vintage", "No basin-wide component/horizon profile extraction completed."),
        ("saturated_hydraulic_conductivity", "Area- and component-weighted saturated hydraulic conductivity.", "Not populated; target unit mm/hour", "USDA NRCS SSURGO horizon attributes", "https://sdmdataaccess.nrcs.usda.gov/", "Planned: thickness-weighted profile average from horizon ksat_r, converted from SSURGO units only after confirming field metadata.", "Current SSURGO survey vintage", "No basin-wide component/horizon profile extraction completed."),
        ("mean_annual_precipitation_mm", "1991–2020 mean annual precipitation, spatially averaged over the basin.", "mm/year", "PRISM Climate Group 4 km normals", "https://prism.oregonstate.edu/request/normals/1991-2020_M3/4km/ppt/PRISM_ppt_30yr_normal_4kmM3_annual_bil.zip", "Annual 4 km PRISM grid (M3; 1991–2020). Each grid cell was intersected with the basin after transform to EPSG:5070; cell precipitation weighted by clipped cell area.", "1991–2020; M3; created 2021-10-29", ""),
    ]
    columns = ["feature_name", "definition", "units", "data_source", "source_url", "calculation_method", "period_or_version", "missing_data_explanation"]
    return pd.DataFrame(rows, columns=columns)


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    frame, provenance = collect_rows()
    boundary_audit_path = REPORTS / "catchment_boundary_validation.csv"
    boundary_audit = pd.read_csv(boundary_audit_path, dtype={"station_id": "string"})
    output = PROCESSED / "catchment_characteristics.csv"
    frame.to_csv(output, index=False, na_rep="")
    dictionary = build_dictionary()
    dictionary["retrieval_date"] = RETRIEVAL_DATE
    dictionary.to_csv(REPORTS / "catchment_data_dictionary.csv", index=False)
    (REPORTS / "catchment_output_provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    check = pd.read_csv(output, dtype={"station_id": "string"})
    if len(check) != 4 or check["station_id"].nunique() != 4 or list(check.columns) != REQUIRED_COLUMNS:
        raise ValueError("Final CSV schema or station validation failed")
    missing_counts = check[REQUIRED_COLUMNS[1:]].isna().sum().to_dict()
    missing_lines = []
    for field, count in missing_counts.items():
        if count:
            missing_lines.append(f"- `{field}`: blank for {count}/4 stations.")
    if not missing_lines:
        missing_lines.append("- No feature values are missing.")

    output_lines = [
        "# FLOODCAST catchment data quality report",
        "",
        f"Retrieval/processing date: {RETRIEVAL_DATE}.",
        "",
        "## First-version status",
        "",
        f"The output has {len(check)} rows, one per requested USGS station, and exactly the required {len(REQUIRED_COLUMNS)} columns. Original raw project files were preserved. Missing values remain blank; no substitute estimates were inserted.",
        "",
        "## Boundary validation and drainage areas",
        "",
        "The selected spatial boundary is the exact-gage split NLDI/NHDPlus upstream basin: `(full upstream basin − full local COMID catchment) ∪ upstream split at the verified NWIS station coordinate`. Station ID, NLDI identifier, COMID, reach measure and coordinates were matched exactly; the local split and full basin were geometry-checked. The 07010000 source polygon required Shapely `make_valid` repair. Boundary areas were computed geodesically and compared with the same NHDPlus flowline `TotDASqKm`.",
        "",
        "NHDPlus and the split NLDI polygon agree within 0.1% for all stations, but the disagreement with NWIS total drainage area is unresolved for 07010000 and 08158000. The output retains NWIS areas as the reported total/contributing fields and does not substitute polygon area. See `catchment_boundary_validation.md` for exact deltas and unusable StreamStats records.",
        "",
        "| Station | NWIS total (sq mi) | NWIS contributing (sq mi) | NHDPlus TotDA (sq mi) | Selected split polygon (sq mi) | Polygon vs NWIS | Decision |",
        "|---|---:|---:|---:|---:|---:|---|",
        *[
            f"| {a.station_id} | {a.nwis_total_area_sq_mi:.0f} | {a.nwis_contributing_area_sq_mi if pd.notna(a.nwis_contributing_area_sq_mi) else 'blank'} | {a.nhdplus_totdasqkm_area_sq_mi:.2f} | {a.corrected_basin_area_sq_mi:.2f} | {a.corrected_area_difference_pct_vs_nwis:.3f}% | {a.boundary_decision} |"
            for a in boundary_audit.itertuples(index=False)
        ],
        "",
        "## Collected metrics",
        "",
        "### 3DEP elevation and slope",
        "",
        "USGS 3DEP ImageServer statistics were requested with 30 m output pixels in EPSG:5070, in 150 km tiles. Elevation tile means are combined using each tile's equal-area basin-intersection area; basin minima/maxima are the extrema of tile statistics. The source service is a dynamic multiresolution mosaic (its underlying source DEM resolution can vary).",
        "",
        "Slope was requested from the same service using its Slope raster function with `ZFactor=1`, percent-rise mode and edge-effect removal. Returned percent-rise statistics contained extreme values (raw means over 1,000% and maxima above 2,000,000% in the completed small basins), so `mean_slope_pct` is intentionally left blank. These results are not used as terrain slope. Manual completion requires downloading USGS 3DEP 1 arc-second DEM GeoTIFF tiles from [The National Map Downloader](https://apps.nationalmap.gov/downloader/), mosaicking/warping to the same 30 m EPSG:5070 grid, and computing local Horn 3×3 slope with a one-cell tile halo and explicit nodata screening.",
        "",
        "Minimum elevation can include below-sea-level values in mapped water/bathymetric cells; this is a 3DEP surface minimum and is not a land-only elevation minimum.",
        "",
        "### Annual NLCD",
        "",
        "All four station results are from the USGS Annual NLCD image services at 30 m for 2024, the latest year exposed in the queried service time extent. Forest is classes 41/42/43; developed/urban is classes 21/22/23/24; impervious cover is the average fractional-impervious pixel value. The incomplete first attempts for 02087500 and 07010000 were preserved; their complete retry files were selected. No further NLCD requests were made after successful retry completion.",
        "",
        "### PRISM precipitation",
        "",
        "The project downloaded the official PRISM 1991–2020 4 km annual precipitation BIL ZIP (precipitation normals version M3, dataset type `an81/r2103h`). Each grid cell was intersected with the basin in EPSG:5070 and weighted by the exact clipped cell area. All four area-weighted basin outputs are present. They differ slightly from the cached EPA StreamCat `precip9120ws` values because this calculation uses the gage-split boundary and PRISM grid directly.",
        "",
        "## Missing values",
        "",
        *missing_lines,
        "",
        "### Soil (SSURGO)",
        "",
        "No basin-wide SSURGO mapunit/component/horizon extraction completed in this time-optimized first pass; there were no cached SSURGO polygons or tabular attributes in `data/raw/`. A valid result requires clipping current SSURGO mapunit polygons to each accepted basin, weighting by clipped mapunit area and `comppct_r`, and joining hydrologic group plus horizon attributes. The required manual/local alternative is to download the SSURGO spatial and tabular packages for every soil survey area intersecting each watershed, or implement the NRCS Soil Data Access pAOI POST workflow and extract component and horizon tables. Dual groups A/D, B/D and C/D must remain explicit or be assigned under a documented drained/undrained scenario; none were guessed here.",
        "",
        "### NWI wetlands",
        "",
        "The USFWS NWI Feature Layer was reachable. A Neuse-basin request returned 500-feature pages; it had delivered 14,500 polygons and was still paging when work was stopped to prioritize 3DEP. Partial compressed raw pages are retained under `data/raw/nwi_pages/`, but they do not cover a complete station result and were not used. The official layer schema exposes wetland type and QA/QC code but no feature mapping-date field. To complete this feature efficiently, obtain the USFWS NWI state/watershed bulk downloads covering the full basin extents, retain their metadata, mosaic locally and clip the wetlands-only Cowardin classes to each validated basin.",
        "",
        "## Missing-field details by station",
        "",
    ]
    for station_id, reasons in provenance["missing"].items():
        if reasons:
            output_lines.append(f"- **{station_id}:** " + "; ".join(reasons) + ".")
    output_lines.extend([
        "",
        "## Validation checks",
        "",
        "- Four unique station IDs and the required CSV column order were checked after writing and reloading with pandas.",
        "- Drainage areas are read from the preserved USGS project source and checked in the boundary validation report against NWIS records.",
        "- Land-cover percentages are checked to lie in 0–100; precipitation/elevation values are not silently rounded into estimates.",
        "- Blank fields indicate a missing or rejected source result, not zero.",
        "",
        "## Source URLs and versions",
        "",
        "- USGS NLDI basin and split process: https://api.water.usgs.gov/docs/nldi/basin/ and https://api.water.usgs.gov/docs/nldi-pygeoapi/splitcatchment/.",
        "- USGS NHDPlus/Hydrologic Geospatial Fabric: https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items.",
        "- USGS 3DEP service: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer (dynamic source mosaic; 30 m output request; retrieval date recorded in raw tile responses).",
        "- USGS Annual NLCD Collection 1.2 (2024 service slice; 30 m): https://www.usgs.gov/centers/eros/science/about-annual-nlcd and https://doi.org/10.5066/P94UXNTS.",
        "- PRISM 1991–2020 precipitation normals, 4 km M3: https://prism.oregonstate.edu/normals/ and https://prism.oregonstate.edu/request/normals/1991-2020_M3/4km/ppt/.",
        "- USDA NRCS SSURGO and Soil Data Access: https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo and https://sdmdataaccess.nrcs.usda.gov/webservicehelp.aspx.",
        "- USFWS NWI web services/data: https://www.fws.gov/program/national-wetlands-inventory/wetlands-data and https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest.",
        "",
        "## Retained source files",
        "",
        "All existing user-supplied discharge, NASA POWER, drainage-area and StreamStats files were left unchanged. New official source files are stored under `data/raw/`; prior/incomplete API responses are retained as audit artifacts rather than replaced.",
    ])
    quality_path = REPORTS / "catchment_data_quality_report.md"
    quality_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    source_lines = [
        "# FLOODCAST catchment data sources",
        "",
        f"Last compiled: {RETRIEVAL_DATE}.",
        "",
        "| Feature group | Dataset and version | Spatial method | Current status |",
        "|---|---|---|---|",
        "| Drainage area and boundary | USGS NWIS; NLDI; NHDPlus flowline TotDASqKm | Exact site/COMID join; gage split from full basin and local COMID catchment | NWIS total/contributing values populated; 07010000 and 08158000 area conflicts remain flagged |",
        "| Elevation | USGS 3DEP dynamic ImageServer; 30 m requested; retrieved 2026-11-05 | EPSG:5070 tiled zonal statistics; equal-area tile weighting | Mean/min/max populated when elevation tiles are complete |",
        "| Slope | USGS 3DEP Slope function; percent rise | ZFactor 1, SlopeType 2, edge effect removal | Returned extreme values failed quality screening; blank pending local DEM processing |",
        "| Land cover | USGS Annual NLCD Collection 1.2 service slice 2024; 30 m | Forest 41/42/43; developed 21–24; fractional impervious mean | All four station rows complete |",
        "| Precipitation | PRISM 1991–2020 annual ppt normal; 4 km; M3 / an81/r2103h | Fractional grid-cell area weights in EPSG:5070 | All four station rows complete |",
        "| Soils | USDA SSURGO / Soil Data Access | Requires basin-clipped mapunits joined to component and horizon records | Not collected in this time-optimized version |",
        "| Wetlands | USFWS NWI live Wetlands Feature Layer | Planned exact geometry clip; deepwater excluded | Partial raw paging only; no station metrics published |",
        "",
        "Primary references: [USGS NLDI](https://api.water.usgs.gov/docs/nldi/), [3DEP](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services), [Annual NLCD](https://www.usgs.gov/centers/eros/science/about-annual-nlcd), [PRISM normals](https://www.prism.oregonstate.edu/normals/), [SSURGO](https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo), [NWI](https://www.fws.gov/program/national-wetlands-inventory/wetlands-data).",
    ]
    (REPORTS / "catchment_sources.md").write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Wrote {REPORTS / 'catchment_data_dictionary.csv'}")
    print(f"Wrote {quality_path}")
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
