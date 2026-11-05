"""Collect validated, pre-aggregated basin characteristics for FLOODCAST stations.

The EPA StreamCat API supplies upstream-watershed summaries indexed by the same
NHDPlusV2 COMIDs returned by the USGS NLDI. This avoids substituting station
point values for watershed values and avoids downloading national raster mosaics.
Fields absent or ambiguous in the source remain blank in the output.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
RETRIEVAL_DATE = date.today().isoformat()

STATIONS = {
    "01646500": {
        "name": "Potomac River near Washington, DC",
        "lat": 38.949778,
        "lon": -77.127639,
    },
    "02087500": {
        "name": "Neuse River near Clayton, NC",
        "lat": 35.647222,
        "lon": -78.405278,
    },
    "07010000": {
        "name": "Mississippi River at St. Louis, MO",
        "lat": 38.629000,
        "lon": -90.179778,
    },
    "08158000": {
        "name": "Colorado River at Austin, TX",
        "lat": 30.246139,
        "lon": -97.680056,
    },
}

NLDI_BASE = "https://api.water.usgs.gov/nldi/linked-data"
FABRIC_BASE = "https://api.water.usgs.gov/fabric/pygeoapi/collections"
STREAMCAT_BASE = "https://api.epa.gov/StreamCat/streams"
NWIS_URL = "https://waterservices.usgs.gov/nwis/site/"
STREAMCAT_METRICS = [
    "elev",
    "precip9120",
    "tmean9120",
    "pctimp2019",
    "pctconif2019",
    "pctdecid2019",
    "pctmxfst2019",
    "pctwdwet2019",
    "pcthbwet2019",
    "pcturbop2019",
    "pcturblo2019",
    "pcturbmd2019",
    "pcturbhi2019",
    "clay",
    "sand",
    "om",
    "rckdep",
    "wtdep",
]


def request_text(url: str, params: dict[str, Any] | None = None) -> str:
    response = requests.get(url, params=params, timeout=180)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def request_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return json.loads(request_text(url, params))


def load_or_fetch(
    path: Path,
    url: str,
    params: dict[str, Any] | None,
    refresh: bool,
) -> str:
    """Reuse saved source responses unless --refresh is explicitly requested."""
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8-sig")
    text = request_text(url, params)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def parse_nwis_rdb(text: str) -> pd.DataFrame:
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if len(lines) < 3:
        raise ValueError("NWIS RDB response is missing its header or data rows")
    # The second RDB line describes column widths/types; it is not a data row.
    return pd.read_csv(StringIO("\n".join([lines[0], *lines[2:]])), sep="\t", dtype=str)


def ring_area_sq_m(ring: list[list[float]]) -> float:
    """Spherical area for one GeoJSON ring, using the WGS84 authalic radius."""
    radius_m = 6_371_007.1809
    total = 0.0
    for first, second in zip(ring, ring[1:]):
        lon1, lat1 = first[:2]
        lon2, lat2 = second[:2]
        total += (lon2 - lon1) * math.pi / 180.0 * (
            2.0
            + math.sin(lat1 * math.pi / 180.0)
            + math.sin(lat2 * math.pi / 180.0)
        )
    return abs(total * radius_m * radius_m / 2.0)


def geometry_area_sq_m(geometry: dict[str, Any]) -> float:
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise ValueError(f"Unsupported basin geometry: {geometry['type']}")
    area = 0.0
    for polygon in polygons:
        if not polygon:
            continue
        area += ring_area_sq_m(polygon[0])
        area -= sum(ring_area_sq_m(ring) for ring in polygon[1:])
    return area


def value(item: dict[str, Any], key: str) -> float | None:
    raw = item.get(key)
    if raw is None or raw == "" or pd.isna(raw):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def sum_available(item: dict[str, Any], keys: list[str]) -> float | None:
    vals = [value(item, key) for key in keys]
    return sum(vals) if all(v is not None for v in vals) else None


def collect(refresh: bool) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    sites = ",".join(STATIONS)
    nwis_path = RAW_DIR / "usgs_station_verification_nwis.rdb"
    nwis_text = load_or_fetch(
        nwis_path,
        NWIS_URL,
        {"format": "rdb", "sites": f"{sites},01646502", "siteOutput": "expanded", "siteStatus": "all"},
        refresh,
    )
    nwis = parse_nwis_rdb(nwis_text).set_index("site_no", drop=False)
    drainage_path = RAW_DIR / "usgs_drainage_areas.csv"
    drainage = pd.read_csv(drainage_path, dtype={"station_id": "string"}).set_index(
        "station_id", drop=False
    )
    if set(STATIONS) - set(nwis.index) or set(STATIONS) - set(drainage.index):
        raise ValueError("A target station is absent from NWIS or the existing drainage CSV")
    if drainage.index.has_duplicates:
        raise ValueError("Duplicate station IDs in usgs_drainage_areas.csv")

    station_records: dict[str, dict[str, Any]] = {}
    flowline_records: dict[str, dict[str, Any]] = {}
    boundaries: dict[str, dict[str, Any]] = {}
    comids: dict[str, int] = {}
    for station_id, expected in STATIONS.items():
        row = nwis.loc[station_id]
        official_name = str(row["station_nm"]).strip()
        lat, lon = float(row["dec_lat_va"]), float(row["dec_long_va"])
        if abs(lat - expected["lat"]) > 0.00005 or abs(lon - expected["lon"]) > 0.00005:
            raise ValueError(f"NWIS coordinate mismatch for {station_id}: {(lat, lon)}")
        if not official_name:
            raise ValueError(f"NWIS returned no station name for {station_id}")

        nldi_station_path = RAW_DIR / f"usgs_nldi_station_{station_id}.geojson"
        nldi_station_url = f"{NLDI_BASE}/nwissite/USGS-{station_id}"
        nldi_station = json.loads(
            load_or_fetch(nldi_station_path, nldi_station_url, {"f": "json"}, refresh)
        )
        feature = nldi_station["features"][0]
        props = feature["properties"]
        if props.get("identifier") != f"USGS-{station_id}":
            raise ValueError(f"NLDI returned a different site for {station_id}")
        comid = int(props["comid"])
        comids[station_id] = comid

        basin_path = RAW_DIR / f"usgs_nldi_basin_{station_id}.geojson"
        basin_url = f"{NLDI_BASE}/nwissite/USGS-{station_id}/basin"
        basin = json.loads(
            load_or_fetch(
                basin_path,
                basin_url,
                {"f": "json", "simplified": "false"},
                refresh,
            )
        )
        if len(basin.get("features", [])) != 1 or not basin["features"][0].get("geometry"):
            raise ValueError(f"NLDI did not return exactly one basin for {station_id}")
        boundaries[station_id] = basin["features"][0]

        flow_path = RAW_DIR / f"usgs_nhdplus_flowline_{station_id}.geojson"
        flow_url = f"{FABRIC_BASE}/nhdflowline_network/items"
        flow = json.loads(
            load_or_fetch(flow_path, flow_url, {"comid": comid, "limit": 1, "f": "json"}, refresh)
        )
        if len(flow.get("features", [])) != 1 or int(flow["features"][0]["properties"]["comid"]) != comid:
            raise ValueError(f"NHDPlus COMID mismatch for {station_id}")
        flowline_records[station_id] = flow["features"][0]["properties"]
        station_records[station_id] = {
            "name": official_name,
            "lat": lat,
            "lon": lon,
            "drainage_area_sq_mi": value(row, "drain_area_va"),
            "contributing_drainage_area_sq_mi": value(row, "contrib_drain_area_va"),
            "comid": comid,
            "reachcode": str(props.get("reachcode", "")),
        }

        # Existing user-supplied values must match the live NWIS record.
        supplied = drainage.loc[station_id]
        supplied_area = value(supplied, "drainage_area_sq_mi")
        if supplied_area is None or abs(supplied_area - station_records[station_id]["drainage_area_sq_mi"]) > 0.01:
            raise ValueError(f"Existing drainage area does not match NWIS for {station_id}")
        supplied_contrib = value(supplied, "contributing_drainage_area_sq_mi")
        official_contrib = station_records[station_id]["contributing_drainage_area_sq_mi"]
        if supplied_contrib != official_contrib:
            raise ValueError(f"Existing contributing area does not match NWIS for {station_id}")

    variable_path = RAW_DIR / "epa_streamcat_variable_info.csv"
    variable_url = f"{STREAMCAT_BASE}/variable_info"
    variable_text = load_or_fetch(variable_path, variable_url, None, refresh)
    variable_info = pd.read_csv(StringIO(variable_text), dtype=str)
    metrics_path = RAW_DIR / "epa_streamcat_watershed_metrics.json"
    metrics_url = f"{STREAMCAT_BASE}/metrics"
    metrics_text = load_or_fetch(
        metrics_path,
        metrics_url,
        {
            "name": ",".join(STREAMCAT_METRICS),
            "areaOfInterest": "ws",
            "comid": ",".join(str(comids[s]) for s in STATIONS),
            "showAreaSqKm": "true",
            "showPctFull": "true",
        },
        refresh,
    )
    metrics_json = json.loads(metrics_text)
    metric_items = metrics_json.get("items", [])
    metrics_by_comid = {int(item["comid"]): item for item in metric_items if item.get("comid") is not None}
    if set(comids.values()) - set(metrics_by_comid):
        raise ValueError("EPA StreamCat omitted one or more requested watershed COMIDs")

    rows: list[dict[str, Any]] = []
    for station_id, site in STATIONS.items():
        item = metrics_by_comid[comids[station_id]]
        flow = flowline_records[station_id]
        basin_geom = boundaries[station_id]["geometry"]
        basin_area_sq_mi = geometry_area_sq_m(basin_geom) / 2_589_988.110336
        nhdplus_area_sq_mi = (value(flow, "totdasqkm") or 0.0) / 2.589988110336
        usgs_area = station_records[station_id]["drainage_area_sq_mi"]
        area_delta_pct = ((basin_area_sq_mi - usgs_area) / usgs_area * 100.0) if usgs_area else None
        forest = sum_available(
            item,
            ["pctconif2019ws", "pctdecid2019ws", "pctmxfst2019ws"],
        )
        urban = sum_available(
            item,
            ["pcturbop2019ws", "pcturblo2019ws", "pcturbmd2019ws", "pcturbhi2019ws"],
        )
        wetland = sum_available(item, ["pctwdwet2019ws", "pcthbwet2019ws"])
        rows.append(
            {
                "station_id": station_id,
                "station_name": station_records[station_id]["name"],
                "latitude": station_records[station_id]["lat"],
                "longitude": station_records[station_id]["lon"],
                "nldiplus_comid": comids[station_id],
                "drainage_area_sq_mi": usgs_area,
                "contributing_drainage_area_sq_mi": station_records[station_id]["contributing_drainage_area_sq_mi"],
                "nldiplus_boundary_area_sq_mi": round(basin_area_sq_mi, 2),
                "nhdplus_total_area_sq_mi": round(nhdplus_area_sq_mi, 2),
                "boundary_area_difference_pct_vs_usgs": round(area_delta_pct, 2) if area_delta_pct is not None else None,
                "mean_elevation_m": value(item, "elevws"),
                "minimum_elevation_m": None,
                "maximum_elevation_m": None,
                "mean_slope_pct": None,
                "impervious_cover_pct": value(item, "pctimp2019ws"),
                "forest_cover_pct": forest,
                "urban_cover_pct": urban,
                "wetland_cover_pct": wetland,
                "soil_group_a_pct": None,
                "soil_group_b_pct": None,
                "soil_group_c_pct": None,
                "soil_group_d_pct": None,
                "soil_clay_pct": value(item, "clayws"),
                "soil_sand_pct": value(item, "sandws"),
                # The API description says cm/hour but its unit column says Percent.
                # Do not publish this ambiguous value as a physical measurement.
                "soil_permeability_cm_hr": None,
                "soil_organic_matter_pct": value(item, "omws"),
                "soil_bedrock_depth_cm": value(item, "rckdepws"),
                "soil_water_table_depth_cm": value(item, "wtdepws"),
                "soil_available_water_capacity": None,
                "mean_annual_precipitation_mm": value(item, "precip9120ws"),
                "mean_annual_temperature_c": value(item, "tmean9120ws"),
            }
        )

    result = pd.DataFrame(rows)
    if len(result) != 4 or result["station_id"].nunique() != 4:
        raise ValueError("Final station table must have exactly four unique stations")
    if set(result["station_id"]) != set(STATIONS):
        raise ValueError("Final station IDs do not exactly match the requested station set")
    if result["drainage_area_sq_mi"].isna().any():
        raise ValueError("A station is missing its verified USGS drainage area")
    required_metrics = [
        "mean_elevation_m",
        "impervious_cover_pct",
        "forest_cover_pct",
        "urban_cover_pct",
        "wetland_cover_pct",
        "soil_clay_pct",
        "soil_sand_pct",
        "soil_organic_matter_pct",
        "soil_bedrock_depth_cm",
        "soil_water_table_depth_cm",
        "mean_annual_precipitation_mm",
        "mean_annual_temperature_c",
    ]
    if result[required_metrics].isna().any().any():
        missing = result.loc[result[required_metrics].isna().any(axis=1), "station_id"].tolist()
        raise ValueError(f"Required returned watershed metrics are missing for {missing}")
    percentage_columns = [
        "impervious_cover_pct",
        "forest_cover_pct",
        "urban_cover_pct",
        "wetland_cover_pct",
        "soil_clay_pct",
        "soil_sand_pct",
        "soil_organic_matter_pct",
    ]
    if ((result[percentage_columns] < 0) | (result[percentage_columns] > 100)).any().any():
        raise ValueError("A percentage metric falls outside the valid 0–100 range")
    if (result[["drainage_area_sq_mi", "mean_elevation_m", "mean_annual_precipitation_mm"]] < 0).any().any():
        raise ValueError("A required nonnegative area/elevation/precipitation value is negative")
    return result, metrics_json, rows


def build_dictionary() -> pd.DataFrame:
    definitions = [
        ("station_id", "USGS site number; preserved as text with leading zeroes.", "USGS station ID", "USGS NWIS Site Service", "Exact NWIS site lookup; confirmed against the target station list.", "Static", ""),
        ("station_name", "Official station name returned by NWIS.", "Text", "USGS NWIS Site Service", "Exact site_no lookup.", "Static", ""),
        ("latitude", "Official NWIS station latitude.", "Decimal degrees", "USGS NWIS Site Service", "Exact site_no lookup; checked against project coordinates.", "Static", ""),
        ("longitude", "Official NWIS station longitude.", "Decimal degrees", "USGS NWIS Site Service", "Exact site_no lookup; checked against project coordinates.", "Static", ""),
        ("nldiplus_comid", "NHDPlusV2 COMID associated by NLDI with the exact USGS site.", "Integer identifier", "USGS NLDI", "Joined by NWIS site ID, not nearest station name.", "Static", ""),
        ("drainage_area_sq_mi", "USGS-reported total drainage area.", "square miles", "USGS NWIS; checked against usgs_drainage_areas.csv", "NWIS drain_area_va; existing project value required to match within 0.01 sq mi.", "Static", ""),
        ("contributing_drainage_area_sq_mi", "USGS-reported contributing drainage area; distinct from total area.", "square miles", "USGS NWIS; checked against usgs_drainage_areas.csv", "NWIS contrib_drain_area_va; missing remains blank.", "Static", "Not reported for three of the four stations."),
        ("nldiplus_boundary_area_sq_mi", "Area of the full NLDI upstream polygon associated with the station COMID.", "square miles", "USGS NLDI basin endpoint", "GeoJSON polygon area calculated on the WGS84 authalic sphere; used as a comparison area, not substituted for NWIS drainage area.", "Static", "Spherical area approximation; see quality report."),
        ("nhdplus_total_area_sq_mi", "Total accumulated drainage area reported for the NHDPlusV2 flowline COMID.", "square miles", "USGS Hydrologic Geospatial Fabric, NHDPlusV2 flowline network", "TotDASqKm converted to square miles using 1 sq mi = 2.589988110336 sq km.", "Static", "NHDPlusV2 area differs materially from NWIS at 07010000 and 08158000."),
        ("boundary_area_difference_pct_vs_usgs", "Percent difference between NLDI polygon area and NWIS total drainage area.", "percent", "USGS NWIS and USGS NLDI", "(NLDI polygon area - NWIS drain_area_va) / NWIS drain_area_va * 100.", "Static", "Large absolute difference indicates a boundary/area reconciliation limitation."),
        ("mean_elevation_m", "Mean elevation for the upstream watershed.", "metres", "EPA StreamCat, NHDPlusV2 Elevation metric", "StreamCat watershed metric elevws for the station COMID.", "Static", "NHDPlusV2 is the documented source; exact elevation raster cell spacing is not exposed by the API metadata."),
        ("minimum_elevation_m", "Minimum watershed elevation.", "metres", "Not collected", "No reliable basin-level minimum returned by the accessed services.", "Static", "Not available from the collected API response."),
        ("maximum_elevation_m", "Maximum watershed elevation.", "metres", "Not collected", "No reliable basin-level maximum returned by the accessed services.", "Static", "Not available from the collected API response."),
        ("mean_slope_pct", "Area-weighted mean terrain slope of the watershed.", "percent rise", "Not collected; 3DEP processing required", "No basin mean slope was returned. NHDPlus channel slope is not substituted for terrain slope.", "Static", "Not available; would require basin-wide terrain processing."),
        ("impervious_cover_pct", "EPA StreamCat watershed fractional imperviousness metric for 2019.", "percent", "EPA StreamCat / NLCD 2019", "Watershed metric pctimp2019ws.", "Static snapshot (2019)", "Metric is EPA's defined imperviousness summary; not a current 2025 NLCD measurement."),
        ("forest_cover_pct", "Combined NLCD 2019 deciduous, evergreen, and mixed forest-class area in the watershed.", "percent of watershed", "EPA StreamCat / NLCD 2019", "Sum of pctdecid2019ws, pctconif2019ws, and pctmxfst2019ws.", "Static snapshot (2019)", "Uses NLCD land-cover classes, not tree-canopy cover."),
        ("urban_cover_pct", "Combined NLCD 2019 developed open-space, low-, medium-, and high-intensity classes.", "percent of watershed", "EPA StreamCat / NLCD 2019", "Sum of pcturbop2019ws, pcturblo2019ws, pcturbmd2019ws, and pcturbhi2019ws.", "Static snapshot (2019)", "Includes developed open space."),
        ("wetland_cover_pct", "Combined NLCD 2019 woody and herbaceous wetland land-cover classes.", "percent of watershed", "EPA StreamCat / NLCD 2019", "Sum of pctwdwet2019ws and pcthbwet2019ws; not USFWS NWI polygon coverage.", "Static snapshot (2019)", "NLCD wetland classes are not interchangeable with NWI wetlands."),
        ("soil_group_a_pct", "Watershed area fraction in NRCS hydrologic soil group A.", "percent", "Not collected; SSURGO required", "No group-A summary returned by StreamCat.", "Static", "Missing; not replaced with a STATSGO soil texture proxy."),
        ("soil_group_b_pct", "Watershed area fraction in NRCS hydrologic soil group B.", "percent", "Not collected; SSURGO required", "No group-B summary returned by StreamCat.", "Static", "Missing; not replaced with a STATSGO soil texture proxy."),
        ("soil_group_c_pct", "Watershed area fraction in NRCS hydrologic soil group C.", "percent", "Not collected; SSURGO required", "No group-C summary returned by StreamCat.", "Static", "Missing; not replaced with a STATSGO soil texture proxy."),
        ("soil_group_d_pct", "Watershed area fraction in NRCS hydrologic soil group D.", "percent", "Not collected; SSURGO required", "No group-D summary returned by StreamCat.", "Static", "Missing; not replaced with a STATSGO soil texture proxy."),
        ("soil_clay_pct", "Mean soil clay content for the upstream watershed.", "percent", "EPA StreamCat / STATSGO", "StreamCat watershed metric clayws.", "Static", "Generalized STATSGO source; lower detail than SSURGO."),
        ("soil_sand_pct", "Mean soil sand content for the upstream watershed.", "percent", "EPA StreamCat / STATSGO", "StreamCat watershed metric sandws.", "Static", "Generalized STATSGO source; lower detail than SSURGO."),
        ("soil_permeability_cm_hr", "Mean saturated/soil permeability for the upstream watershed.", "cm/hour", "EPA StreamCat / STATSGO", "Value withheld because the API description says cm/hour while the API unit field says Percent.", "Static", "Ambiguous units in source metadata; values intentionally blank."),
        ("soil_organic_matter_pct", "Mean soil organic matter content by weight.", "percent", "EPA StreamCat / STATSGO", "StreamCat watershed metric omws.", "Static", "Generalized STATSGO source; lower detail than SSURGO."),
        ("soil_bedrock_depth_cm", "Mean soil depth to bedrock.", "centimetres", "EPA StreamCat / STATSGO", "StreamCat watershed metric rckdepws.", "Static", "Generalized STATSGO source; lower detail than SSURGO."),
        ("soil_water_table_depth_cm", "Mean seasonal water-table depth.", "centimetres", "EPA StreamCat / STATSGO", "StreamCat watershed metric wtdepws.", "Static", "Generalized STATSGO source; lower detail than SSURGO."),
        ("soil_available_water_capacity", "Soil available-water capacity.", "not assigned", "Not collected; SSURGO required", "No basin-level AWC metric returned by the accessed services.", "Static", "Missing; no proxy substituted."),
        ("mean_annual_precipitation_mm", "PRISM annual-normal precipitation averaged over the watershed for 1991–2020.", "millimetres/year", "EPA StreamCat / PRISM 1991–2020", "StreamCat watershed metric precip9120ws.", "Static climate normal (1991–2020)", "Basin summary; not a station-point value."),
        ("mean_annual_temperature_c", "PRISM annual-normal mean temperature averaged over the watershed for 1991–2020.", "degrees Celsius", "EPA StreamCat / PRISM 1991–2020", "StreamCat watershed metric tmean9120ws.", "Static climate normal (1991–2020)", "Basin summary; not a station-point value."),
    ]
    return pd.DataFrame(
        definitions,
        columns=[
            "feature_name",
            "description",
            "unit",
            "data_source",
            "calculation_or_aggregation_method",
            "static_or_time_varying",
            "missing_data_explanation",
        ],
    ).assign(retrieval_date=RETRIEVAL_DATE)[
        [
            "feature_name",
            "description",
            "unit",
            "data_source",
            "retrieval_date",
            "calculation_or_aggregation_method",
            "static_or_time_varying",
            "missing_data_explanation",
        ]
    ]


def write_reports(data: pd.DataFrame, metrics: dict[str, Any], output_path: Path) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    build_dictionary().to_csv(REPORTS_DIR / "catchment_data_dictionary.csv", index=False)
    areas = data.set_index("station_id")
    lines = [
        "# FLOODCAST catchment data quality report",
        "",
        f"Retrieval date: {RETRIEVAL_DATE} (Asia/Kolkata project date).",
        "",
        "## Summary",
        "",
        "The final CSV contains exactly four target stations and no duplicate IDs. NWIS station metadata and drainage areas were checked against the existing `data/raw/usgs_drainage_areas.csv`. The 01646500 result is keyed to the exact NWIS ID; 01646502 was queried only to confirm that it is a separate adjusted record at the same coordinates and was not used as the target station.",
        "",
        "Watershed characteristics come from EPA StreamCat `watershed` metrics keyed by USGS NLDI COMID. NLDI polygons are saved under `data/raw/usgs_nldi_basin_*.geojson`; matching NHDPlusV2 flowline `TotDASqKm` attributes are saved under `data/raw/usgs_nhdplus_flowline_*.geojson`. StreamCat's COMID watershed can include the complete local catchment; it is not clipped at the station's reach measure. The first exact-gage `splitCatchment=true` test for 01646500 returned an upstream 502/400 error, so no split polygons were accepted or requested for the other three sites. These values are explicitly flagged as COMID-watershed summaries pending exact-gage-boundary reconciliation. StreamStats returned HTTP 200 for all four stations, but three results (01646500, 07010000, 08158000) explicitly warned that the point was not snappable and returned only a tiny cell; those polygons were rejected. StreamStats did return a valid delineation at 02087500, but the consistent COMID source used here is NLDI/NHDPlusV2 for all four stations.",
        "",
        "## Boundary-area cross-check",
        "",
        "The NLDI polygon area uses an authalic-sphere calculation from the returned GeoJSON, while NWIS drainage area is the published station value. NHDPlusV2 `TotDASqKm` independently agrees closely with the NLDI polygon-area calculation. The differences below are retained as a quality flag; the NHDPlus polygon area is not substituted for the NWIS drainage-area column.",
        "",
        "| Station | NWIS total (sq mi) | NLDI polygon (sq mi) | NHDPlus total (sq mi) | NLDI vs NWIS |",
        "|---|---:|---:|---:|---:|",
    ]
    for station_id, row in areas.iterrows():
        lines.append(
            f"| {station_id} | {row['drainage_area_sq_mi']:.0f} | {row['nldiplus_boundary_area_sq_mi']:.2f} | {row['nhdplus_total_area_sq_mi']:.2f} | {row['boundary_area_difference_pct_vs_usgs']:.2f}% |"
        )
    lines += [
        "",
        "The NWIS and NLDI/NHDPlus total areas are close for 01646500 (about -0.06%) and 02087500 (about +0.31%). NHDPlus is about 4.3% lower than NWIS at 07010000 and about 11.0% lower at 08158000. Those mismatches are material and require review before using area-sensitive model features. For 08158000, USGS reports total area 39,009 sq mi and contributing area 27,606 sq mi; neither value is replaced by the NHDPlus area (~34,710 sq mi). The reason for these two discrepancies was not established in this collection phase.",
        "",
        "## Collected coverage by station",
        "",
        "| Station | Mean elevation | Land cover (impervious / forest / urban / wetlands) | STATSGO soil summaries | PRISM normals |",
        "|---|---|---|---|---|",
    ]
    for station_id, row in areas.iterrows():
        lines.append(
            f"| {station_id} | {row['mean_elevation_m']:.2f} m | {row['impervious_cover_pct']:.2f}% / {row['forest_cover_pct']:.2f}% / {row['urban_cover_pct']:.2f}% / {row['wetland_cover_pct']:.2f}% | clay {row['soil_clay_pct']:.2f}%; sand {row['soil_sand_pct']:.2f}%; organic matter {row['soil_organic_matter_pct']:.2f}% | {row['mean_annual_precipitation_mm']:.1f} mm; {row['mean_annual_temperature_c']:.2f} °C |"
        )
    lines += [
        "",
        "## Missing or limited features",
        "",
        "- Mean terrain slope, minimum elevation, and maximum elevation are blank. The NHDPlus `slope` attribute is stream/channel slope, not mean basin terrain slope, and was not substituted. Basin-wide terrain processing from 3DEP remains outstanding.",
        "- NLDI station records include a reach measure; the basin requests used the default unsplit local catchment. A test `splitCatchment=true` request for 01646500 failed with an upstream service error, so no split-boundary requests completed for any of the four sites. Treat COMID watershed metrics as basin-level approximations until station-specific split boundaries can be validated.",
        "- Hydrologic soil group A/B/C/D percentages and available water capacity are blank. EPA StreamCat does not return these fields. Available soil values are lower-detail STATSGO summaries (clay, sand, organic matter, bedrock depth, and seasonal water-table depth), not SSURGO AOI summaries.",
        "- Soil permeability is blank because EPA's metric description states cm/hour while its unit metadata says Percent. The value was withheld due to this conflict.",
        "- Wetland percentage is the sum of NLCD 2019 woody and herbaceous wetland classes. It is not an NWI polygon-derived wetland percentage.",
        "- Land-cover summaries use NLCD 2019, not the latest 2025 release. This is a fixed static snapshot near the middle of the 2010–2025 discharge record; it can still introduce temporal mismatch for early years.",
        "- StreamCat's elevation metric is documented as NHDPlusV2 mean AOI elevation in metres. Its endpoint metadata does not state the original elevation raster cell spacing, so no raster resolution is asserted here. Precipitation and temperature are 1991–2020 PRISM normals summarized by EPA at watershed scale.",
        "- The StreamCat response did not expose per-metric percent-full/completeness values despite the request parameter; absence of a returned metric is treated as missing rather than zero.",
        "",
        "## Validation",
        "",
        f"- Four rows and four unique station IDs: {len(data)} / {data['station_id'].nunique()}.",
        "- Exact target IDs checked through NWIS and NLDI; no 01646502 data used.",
        "- Existing drainage areas checked against live NWIS `drain_area_va` and `contrib_drain_area_va` values.",
        "- Null feature values remain blank in CSV; no missing values were filled with zero.",
        "- All area values in the NWIS columns are square miles; NHDPlus square kilometres were converted to square miles only for the comparison column.",
        "- Existing USGS and NASA POWER raw CSVs were not modified.",
        "- The current workspace's `.venv` points to an unavailable Microsoft Store Python executable. CSV content and row/key integrity were checked with PowerShell/Node; pandas execution could not be run here. Run `python src/prepare_catchment_characteristics.py` in a working environment with the existing pandas/requests requirements to regenerate and perform the script's pandas checks.",
        "",
        "## Next manual collection needed",
        "",
        "1. Obtain and validate NLDI split-catchment boundaries at each gage measure; reconcile the 07010000 and 08158000 NWIS-vs-NHDPlus area differences before finalizing area-sensitive features.",
        "2. Extract mean terrain slope and min/max elevation from one consistently available 3DEP seamless DEM over the accepted basin polygons.",
        "3. Run a basin-polygon SSURGO overlay for hydrologic soil group fractions and available water capacity.",
        "4. Extract PRISM 1991–2020 normals directly from one documented grid resolution over the accepted polygons if exact split-basin precipitation is required.",
        "5. If wetland definition specifically means mapped NWI wetlands, replace/augment the NLCD wetland proxy with an NWI polygon overlay and document map dates.",
    ]
    (REPORTS_DIR / "catchment_data_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    sources = [
        "# Catchment data sources",
        "",
        f"Retrieved {RETRIEVAL_DATE}. Original responses used to produce the dataset are preserved in `data/raw/`.",
        "",
        "## Station identity and drainage areas",
        "",
        "- USGS NWIS Site Service: `https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=01646500,02087500,07010000,08158000,01646502&siteOutput=expanded&siteStatus=all`.",
        "  - Local response: `data/raw/usgs_station_verification_nwis.rdb`.",
        "  - Used `drain_area_va`, `contrib_drain_area_va`, exact `site_no`, station name, and decimal coordinates.",
        "  - 01646502 was fetched only as a station-identity comparison. It is not in the output.",
        "- Existing user data: `data/raw/usgs_drainage_areas.csv`; retained unchanged and compared with NWIS.",
        "",
        "## Watershed boundary and NHDPlus cross-check",
        "",
        "- USGS NLDI station feature: `https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{station_id}?f=json`.",
        "- USGS NLDI full basin: `https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{station_id}/basin?f=json&simplified=false`.",
        "  - Local responses: `data/raw/usgs_nldi_station_{station_id}.geojson` and `data/raw/usgs_nldi_basin_{station_id}.geojson`.",
        "  - NLDI uses NHDPlusV2; basin polygons are keyed to the exact NWIS site record and COMID. The default basin request uses the whole local catchment; a `splitCatchment=true` request was attempted but the service returned an upstream 502/400 error.",
        "- USGS Hydrologic Geospatial Fabric: `https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_network/items?comid={COMID}&limit=1&f=json`.",
        "  - Local responses: `data/raw/usgs_nhdplus_flowline_{station_id}.geojson`.",
        "  - `TotDASqKm` is converted to square miles for boundary-area comparison.",
        "- The new StreamStats endpoint was tested: `https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}?lat={lat}&lon={lon}`. Three responses warned that the point was not snappable and returned only a small cell, so those results were rejected. Saved responses are `data/raw/streamstats_ssdelineate_{station_id}.json`.",
        "",
        "## Basin characteristics",
        "",
        "- EPA StreamCat watershed metrics API: `https://api.epa.gov/StreamCat/streams/metrics?name={metrics}&areaOfInterest=ws&comid={COMIDs}&showAreaSqKm=true&showPctFull=true`.",
        "  - Local response: `data/raw/epa_streamcat_watershed_metrics.json`.",
        "  - API metric registry: `https://api.epa.gov/StreamCat/streams/variable_info`; local copy `data/raw/epa_streamcat_variable_info.csv`.",
        "  - Framework: NHDPlusV2, with watershed values defined as the focal catchment plus all upstream connected catchments.",
        "- StreamCat NLCD metrics used 2019 classes: imperviousness, forest classes 41–43, developed classes 21–24, wetland classes 90 and 95. The registry records the NLCD source and retrieval date 2021-08-06 (impervious layer: 2021-08-17). NLCD source resolution: 30 m.",
        "- StreamCat PRISM normal metrics: `precip9120` and `tmean9120`, representing 1991–2020 annual normals; the StreamCat registry records 2023-10-10. Precipitation units are mm; temperature units °C.",
        "- StreamCat soil metrics: STATSGO-derived `clay`, `sand`, `om`, `rckdep`, and `wtdep`. Registry source dates are 2016. `perm` was not used because its description and unit metadata conflict. STATSGO is a generalized soil source, not SSURGO.",
        "- StreamCat `elev` is documented as mean AOI elevation from NHDPlusV2 in metres. The API registry does not provide the source raster's exact cell spacing.",
        "",
        "## Recommended source plan for remaining exact-basin statistics",
        "",
        "| Feature | Preferred source and access | Coverage/version | Exact-basin extraction |",
        "|---|---|---|---|",
        "| Boundary | USGS NLDI basin endpoint with `splitCatchment=true`; retry or use USGS StreamStats only after a station-specific snap succeeds | NHDPlusV2 CONUS network; station features return COMID and reach measure | Validate polygon identity and projected area against NWIS total and contributing areas before using it |",
        "| Mean/min/max elevation and mean terrain slope | USGS 3DEP seamless 1/3 arc-second DEM via The National Map | Full CONUS coverage; approximately 10 m north-south cell spacing, east-west varies with latitude | Clip/mask the same DEM product to each accepted split basin; calculate elevation summaries and area-weighted terrain slope; record vertical datum and actual tiles |",
        "| Impervious, forest, land cover | USGS Annual NLCD Collection 1.2 (2025) or a consistent 2019 snapshot | CONUS; 30 m annual land-cover record, 1985–2025 | Overlay class pixels on accepted basin; document whether imperviousness is a class or fractional impervious layer and compute area percentages |",
        "| Soil groups and available water capacity | USDA NRCS SSURGO via Web Soil Survey / Soil Data Access | CONUS survey areas with variable map scales; annual soil refresh | Intersect map units with basin, weight component attributes by map-unit/component area, and compute HSG/AWC area-weighted summaries; retain dual hydrologic groups explicitly |",
        "| Mean annual precipitation | PRISM 1991–2020 annual precipitation normals | CONUS; choose and record a consistent 4 km or 800 m grid | Area-weight grid values over each accepted split basin; do not sample at station coordinates |",
        "| Wetland percentage | USFWS National Wetlands Inventory Wetlands Data Layer download or web services | CONUS; data layer updated twice yearly with local mapping-vintage differences | Intersect and union mapped wetland polygons with accepted basin; calculate area percent and report NWI map dates/coverage gaps |",
        "",
        "## Official reference documentation",
        "",
        "- USGS NLDI basin endpoint and `splitCatchment` behavior: `https://api.water.usgs.gov/docs/nldi/basin/`.",
        "- EPA StreamCat dataset, framework, and metrics: `https://www.epa.gov/national-aquatic-resource-surveys/streamcat-dataset` and `https://www.epa.gov/national-aquatic-resource-surveys/streamcat-metrics-and-definitions`.",
        "- USGS Annual NLCD Collection 1.2 (2025) and 30 m land-cover products: `https://www.usgs.gov/centers/eros/science/usgs-eros-archive-land-cover-annual-nlcd-collection-1-land-cover`.",
        "- PRISM 1991–2020 normals and spatial resolutions: `https://www.prism.oregonstate.edu/normals/`.",
        "- USGS 3DEP DEM products and resolutions: `https://www.usgs.gov/3d-elevation-program/about-3dep-products-services`.",
        "- USDA SSURGO overview, map data, attributes, and access: `https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo`.",
        "- USFWS NWI wetlands layer, downloads, web services, and coverage: `https://www.fws.gov/program/national-wetlands-inventory/wetlands-data`.",
        "",
        "## Unused or not collected",
        "",
        "- 3DEP raster data: no raw raster was downloaded or processed; terrain slope and elevation extrema remain missing.",
        "- SSURGO/AWC/HSG: no SSURGO basin overlay was completed; hydrologic group and available-water-capacity columns remain blank.",
        "- USFWS NWI: no NWI polygon overlay was completed. The dataset's wetland column is explicitly an NLCD 2019 proxy.",
    ]
    (REPORTS_DIR / "catchment_sources.md").write_text("\n".join(sources) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch current API responses and replace only this script's named response files in data/raw/.",
    )
    args = parser.parse_args()
    data, metrics, _ = collect(refresh=args.refresh)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / "catchment_characteristics.csv"
    data.to_csv(output_path, index=False, na_rep="")
    write_reports(data, metrics, output_path)
    # Reload through pandas to verify output schema, key uniqueness, and row count.
    check = pd.read_csv(output_path, dtype={"station_id": "string"})
    if len(check) != 4 or check["station_id"].nunique() != 4:
        raise ValueError("Pandas reload validation failed")
    if set(check["station_id"]) != set(STATIONS):
        raise ValueError("Pandas reload changed a station ID or its leading zeroes")
    if check["drainage_area_sq_mi"].isna().any():
        raise ValueError("Pandas reload found a missing verified drainage area")
    print(f"Wrote {output_path} with {len(check)} unique stations")
    print(f"Wrote {REPORTS_DIR / 'catchment_data_dictionary.csv'}")
    print(f"Wrote {REPORTS_DIR / 'catchment_data_quality_report.md'}")
    print(f"Wrote {REPORTS_DIR / 'catchment_sources.md'}")


if __name__ == "__main__":
    main()
