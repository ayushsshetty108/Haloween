"""Clip USFWS NWI wetland polygons to the validated USGS station basins."""

from __future__ import annotations

import argparse
import gzip
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.geometry.polygon import orient


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PAGE_DIR = RAW / "nwi_pages"
QUERY_URL = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query"
STATIONS = ("01646500", "02087500", "07010000", "08158000")
PAGE_SIZE = 500
INCLUDE_TYPES = {
    "Estuarine and Marine Wetland",
    "Freshwater Emergent Wetland",
    "Freshwater Forested/Shrub Wetland",
}


def esri_polygon(geometry) -> dict[str, Any]:
    parts = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
    rings: list[list[list[float]]] = []
    for part in parts:
        if not isinstance(part, Polygon):
            continue
        p = orient(part, sign=-1.0)
        rings.append([[float(x), float(y)] for x, y in p.exterior.coords])
        rings.extend([[[float(x), float(y)] for x, y in ring.coords] for ring in p.interiors])
    return {"rings": rings, "spatialReference": {"wkid": 3857}}


def request_page(params: dict[str, Any]) -> dict[str, Any]:
    error = ""
    for attempt in range(6):
        try:
            response = requests.post(QUERY_URL, data=params, timeout=(30, 240))
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(json.dumps(payload["error"]))
            return payload
        except Exception as exc:
            error = str(exc)
            if attempt < 5:
                time.sleep(min(2**attempt, 30))
    raise RuntimeError(error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations", nargs="+", default=list(STATIONS), choices=STATIONS)
    args = parser.parse_args()
    PAGE_DIR.mkdir(parents=True, exist_ok=True)
    output_rows = []
    for station_id in args.stations:
        boundary_path = RAW / f"usgs_nldi_validated_basin_{station_id}.geojson"
        boundary = gpd.read_file(boundary_path)
        if len(boundary) != 1 or str(boundary.iloc[0]["station_id"]) != station_id:
            raise ValueError(f"Validated basin station identity mismatch for {station_id}")
        basin = boundary.to_crs("EPSG:5070").geometry.iloc[0]
        basin_3857 = boundary.to_crs("EPSG:3857").geometry.iloc[0]
        geometry_json = json.dumps(esri_polygon(basin_3857), separators=(",", ":"))
        offset = 0
        object_ids: set[int] = set()
        total_area_sq_m = 0.0
        features_seen = 0
        wetland_features_used = 0
        qaqc_codes: dict[str, int] = {}
        page_index = 0
        while True:
            params = {
                "where": "1=1",
                "geometry": geometry_json,
                "geometryType": "esriGeometryPolygon",
                "inSR": "3857",
                "outSR": "5070",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "OBJECTID,WETLAND_TYPE,ATTRIBUTE,QAQC_CODE,ACRES",
                "returnGeometry": "true",
                "returnTrueCurves": "false",
                "resultRecordCount": PAGE_SIZE,
                "resultOffset": offset,
                "orderByFields": "OBJECTID",
                "f": "geojson",
            }
            payload = request_page(params)
            features = payload.get("features", [])
            if not features:
                break
            raw_page_path = PAGE_DIR / f"nwi_{station_id}_{page_index:06d}.geojson.gz"
            with gzip.open(raw_page_path, "wt", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            for feature in features:
                props = feature.get("properties", {})
                object_id = props.get("OBJECTID")
                if object_id is not None and int(object_id) in object_ids:
                    continue
                if object_id is not None:
                    object_ids.add(int(object_id))
                features_seen += 1
                wetland_type = str(props.get("WETLAND_TYPE", ""))
                # NWI also maps deepwater habitats (for example Riverine, Lake and
                # Freshwater Pond); the required wetland-only total excludes these.
                if wetland_type not in INCLUDE_TYPES or not feature.get("geometry"):
                    continue
                geom = shape(feature["geometry"])
                if not geom.is_valid:
                    geom = geom.buffer(0)
                clipped = geom.intersection(basin)
                if clipped.is_empty:
                    continue
                total_area_sq_m += clipped.area
                wetland_features_used += 1
                code = str(props.get("QAQC_CODE") or "<blank>")
                qaqc_codes[code] = qaqc_codes.get(code, 0) + 1
            print(json.dumps({"station_id": station_id, "page": page_index, "features": len(features), "offset": offset}), flush=True)
            if len(features) < PAGE_SIZE or not payload.get("exceededTransferLimit", False):
                # With pagination enabled, offset advances even when the server
                # does not report exceededTransferLimit until the terminal page.
                if len(features) < PAGE_SIZE:
                    break
            offset += len(features)
            page_index += 1
        basin_area_sq_m = basin.area
        result = {
            "station_id": station_id,
            "boundary_file": boundary_path.name,
            "service": "USFWS National Wetlands Inventory Wetlands Feature Layer (MapServer/0)",
            "service_url": "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0",
            "retrieved_date": date.today().isoformat(),
            "wetland_types_included": sorted(INCLUDE_TYPES),
            "deepwater_rule": "Exclude Estuarine and Marine Deepwater, Riverine, Lake, Freshwater Pond, Other, and blank/unmapped types; only the three explicit WETLAND_TYPE wetland categories above are counted.",
            "feature_count_returned": features_seen,
            "wetland_features_intersecting": wetland_features_used,
            "mapped_wetland_area_sq_km": total_area_sq_m / 1_000_000.0,
            "basin_projected_area_sq_km": basin_area_sq_m / 1_000_000.0,
            "wetland_cover_pct": 100.0 * total_area_sq_m / basin_area_sq_m,
            "qaqc_code_feature_counts": qaqc_codes,
            "geometry_calculation": "Each returned NWI wetland polygon was transformed by the service to EPSG:5070, intersected with the validated station basin, and its clipped area summed. Feature OBJECTIDs were deduplicated across pages.",
            "mapping_date_limitation": "The live layer schema exposes OBJECTID, ATTRIBUTE, WETLAND_TYPE, QAQC_CODE and ACRES, but no mapped-date field. Retrieval date is recorded; per-feature source mapping dates are not exposed by this service response.",
            "complete": True,
            "page_count": page_index + 1,
        }
        output = RAW / f"nwi_wetland_zonal_{station_id}.json"
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        output_rows.append(result)
        print(json.dumps({"station_id": station_id, "complete": True, "feature_count": features_seen, "wetland_area_sq_km": result["mapped_wetland_area_sq_km"], "wetland_pct": result["wetland_cover_pct"], "pages": result["page_count"]}), flush=True)
    import pandas as pd
    pd.DataFrame(output_rows).to_csv(RAW / "nwi_wetland_zonal_summary.csv", index=False)


if __name__ == "__main__":
    main()
