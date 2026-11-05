"""Calculate 2024 Annual NLCD watershed cover statistics using official image services."""

from __future__ import annotations

import concurrent.futures
import argparse
import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.geometry.polygon import orient


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SERVICE_BASE = "https://di-nlcd.img.arcgis.com/arcgis/rest/services"
LAND_COVER_SERVICE = SERVICE_BASE + "/USA_NLCD_Annual_LandCover/ImageServer/computeStatisticsHistograms"
IMPERVIOUS_SERVICE = SERVICE_BASE + "/USA_NLCD_Annual_LandCover_Fractional_Impervious_Surface/ImageServer/computeStatisticsHistograms"
YEAR = 2024  # newest year exposed by both official image services at retrieval time
PIXEL_M = 30
TILE_M = 180_000
STATIONS = ("01646500", "02087500", "07010000", "08158000")
MOSAIC_RULE = {
    "mosaicMethod": "esriMosaicAttribute",
    "where": f"Year = {YEAR}",
    "sortField": "Year",
    "sortValue": YEAR,
    "ascending": True,
    "mosaicOperation": "MT_FIRST",
}


def esri_polygon(geometry) -> dict[str, Any]:
    parts = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
    rings: list[list[list[float]]] = []
    for part in parts:
        if isinstance(part, Polygon):
            p = orient(part, sign=-1.0)
            rings.append([[float(x), float(y)] for x, y in p.exterior.coords])
            rings.extend([[[float(x), float(y)] for x, y in ring.coords] for ring in p.interiors])
    return {"rings": rings, "spatialReference": {"wkid": 5070}}


def tile_geometries(geometry):
    minx, miny, maxx, maxy = geometry.bounds
    x0, y0 = math.floor(minx / TILE_M) * TILE_M, math.floor(miny / TILE_M) * TILE_M
    x1, y1 = math.ceil(maxx / TILE_M) * TILE_M, math.ceil(maxy / TILE_M) * TILE_M
    for iy, y in enumerate(range(y0, y1, TILE_M)):
        for ix, x in enumerate(range(x0, x1, TILE_M)):
            part = geometry.intersection(box(x, y, x + TILE_M, y + TILE_M))
            if not part.is_empty and part.area > 0:
                yield f"{ix}_{iy}", part.simplify(5.0, preserve_topology=True)


def get_stats(url: str, tile_id: str, geometry, variable: str) -> dict[str, Any]:
    params = {
        "f": "json",
        "geometry": json.dumps(esri_polygon(geometry), separators=(",", ":")),
        "geometryType": "esriGeometryPolygon",
        "inSR": "5070",
        "pixelSize": json.dumps({"x": PIXEL_M, "y": PIXEL_M, "spatialReference": {"wkid": 5070}}, separators=(",", ":")),
        "mosaicRule": json.dumps(MOSAIC_RULE, separators=(",", ":")),
    }
    last_error = ""
    for attempt in range(7):
        try:
            response = requests.post(url, data=params, timeout=(20, 240))
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(json.dumps(payload["error"]))
            stats = payload.get("statistics") or []
            if not stats or int(stats[0].get("count", 0)) <= 0:
                raise RuntimeError("No valid NLCD cells returned")
            return {"tile_id": tile_id, "variable": variable, "response": payload}
        except Exception as exc:
            last_error = str(exc)
            if attempt < 6:
                time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"{tile_id} {variable}: {last_error}")


def hist_counts(payload: dict[str, Any]) -> dict[int, int]:
    histograms = payload.get("histograms") or []
    if not histograms:
        raise ValueError("Annual NLCD did not return the class histogram needed for area proportions")
    hist = histograms[0]
    size = int(hist["size"])
    minimum, maximum = float(hist["min"]), float(hist["max"])
    step = (maximum - minimum) / size
    return {
        int(round(minimum + (index + 0.5) * step)): int(count)
        for index, count in enumerate(hist["counts"])
        if int(count) > 0
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations", nargs="+", default=list(STATIONS), choices=STATIONS)
    parser.add_argument("--suffix", default="", help="Optional filename suffix for a retry without replacing prior raw responses.")
    args = parser.parse_args()
    out_rows = []
    suffix = f"_{args.suffix}" if args.suffix else ""
    for station_id in args.stations:
        boundary = RAW / f"usgs_nldi_validated_basin_{station_id}.geojson"
        gdf = gpd.read_file(boundary)
        if len(gdf) != 1 or str(gdf.iloc[0]["station_id"]) != station_id:
            raise ValueError(f"Boundary station identity mismatch for {station_id}")
        basin = gdf.to_crs("EPSG:5070").geometry.iloc[0]
        tiles = list(tile_geometries(basin))
        station_data: dict[str, Any] = {
            "station_id": station_id,
            "boundary_file": boundary.name,
            "year": YEAR,
            "collection": "Annual NLCD Collection 1.2 image services; 30 m CONUS",
            "retrieved_date": date.today().isoformat(),
            "processing_crs": "EPSG:5070",
            "pixel_size_m": PIXEL_M,
            "land_cover_service": LAND_COVER_SERVICE.rsplit("/computeStatisticsHistograms", 1)[0],
            "fractional_impervious_service": IMPERVIOUS_SERVICE.rsplit("/computeStatisticsHistograms", 1)[0],
            "tile_count": len(tiles),
            "complete": False,
            "tiles": {},
        }
        for variable, url in (("land_cover", LAND_COVER_SERVICE), ("impervious", IMPERVIOUS_SERVICE)):
            results = []
            errors = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(get_stats, url, tid, geom, variable) for tid, geom in tiles]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        errors.append(str(exc))
            results.sort(key=lambda item: item["tile_id"])
            station_data["tiles"][variable] = results
            station_data.setdefault("errors", []).extend(errors)
            station_data[f"{variable}_complete"] = not errors and len(results) == len(tiles)
        station_data["complete"] = station_data["land_cover_complete"] and station_data["impervious_complete"]
        class_counts: dict[int, int] = {}
        for result in station_data["tiles"]["land_cover"]:
            for class_value, count in hist_counts(result["response"]).items():
                class_counts[class_value] = class_counts.get(class_value, 0) + count
        valid_pixels = sum(class_counts.values())
        if valid_pixels:
            forest_pixels = sum(class_counts.get(code, 0) for code in (41, 42, 43))
            urban_pixels = sum(class_counts.get(code, 0) for code in (21, 22, 23, 24))
            station_data["land_cover_class_counts"] = class_counts
            station_data["valid_land_cover_pixels"] = valid_pixels
            station_data["forest_cover_pct"] = 100.0 * forest_pixels / valid_pixels
            station_data["urban_cover_pct"] = 100.0 * urban_pixels / valid_pixels
        imp_count = 0
        imp_sum = 0.0
        for result in station_data["tiles"]["impervious"]:
            stat = result["response"]["statistics"][0]
            count = int(stat["count"])
            imp_count += count
            imp_sum += float(stat["mean"]) * count
        if imp_count:
            station_data["impervious_cover_pct"] = imp_sum / imp_count
            station_data["valid_impervious_pixels"] = imp_count
        output = RAW / f"annual_nlcd_2024_zonal_{station_id}{suffix}.json"
        output.write_text(json.dumps(station_data, indent=2), encoding="utf-8")
        row = {
            "station_id": station_id,
            "complete": station_data["complete"],
            "tile_count": len(tiles),
            "impervious_cover_pct": station_data.get("impervious_cover_pct"),
            "forest_cover_pct": station_data.get("forest_cover_pct"),
            "urban_cover_pct": station_data.get("urban_cover_pct"),
            "valid_land_cover_pixels": station_data.get("valid_land_cover_pixels"),
            "valid_impervious_pixels": station_data.get("valid_impervious_pixels"),
            "source_file": output.name,
        }
        out_rows.append(row)
        print(json.dumps(row), flush=True)
    import pandas as pd
    pd.DataFrame(out_rows).to_csv(RAW / f"annual_nlcd_2024_zonal_summary{suffix}.csv", index=False)


if __name__ == "__main__":
    main()
