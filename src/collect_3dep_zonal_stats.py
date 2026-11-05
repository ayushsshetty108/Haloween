"""Extract consistent 30 m USGS 3DEP elevation and slope statistics by basin.

The ImageServer applies zonal statistics to geometry-clipped, equal-area tiles.
Source geometries and responses are saved separately from user-supplied raw files.
"""

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
OUT_DIR = RAW / "usgs_3dep_zonal_tiles"
SERVICE = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/computeStatisticsHistograms"
PIXEL_M = 30
TILE_M = 150_000  # margin below 3DEP's 8,000-pixel limit at its roughly 20–30 m base cell size.
SLOPE_RULE = {
    "rasterFunction": "Slope",
    "rasterFunctionArguments": {
        "ZFactor": 1,
        "SlopeType": 2,  # percent rise
        "RemoveEdgeEffect": True,
        "DEM": "$$",
    },
    "outputPixelType": "F32",
    "variableName": "DEM",
}
STATIONS = ("01646500", "02087500", "07010000", "08158000")


def esri_polygon(geometry) -> dict[str, Any]:
    parts = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
    rings: list[list[list[float]]] = []
    for part in parts:
        if not isinstance(part, Polygon):
            continue
        oriented = orient(part, sign=-1.0)  # ESRI outer clockwise, holes counter-clockwise.
        rings.append([[float(x), float(y)] for x, y in oriented.exterior.coords])
        rings.extend([[[float(x), float(y)] for x, y in ring.coords] for ring in oriented.interiors])
    return {"rings": rings, "spatialReference": {"wkid": 5070}}


def tile_geometries(geometry):
    minx, miny, maxx, maxy = geometry.bounds
    x0 = math.floor(minx / TILE_M) * TILE_M
    y0 = math.floor(miny / TILE_M) * TILE_M
    x1 = math.ceil(maxx / TILE_M) * TILE_M
    y1 = math.ceil(maxy / TILE_M) * TILE_M
    for iy, y in enumerate(range(y0, y1, TILE_M)):
        for ix, x in enumerate(range(x0, x1, TILE_M)):
            tile = box(x, y, x + TILE_M, y + TILE_M)
            part = geometry.intersection(tile)
            if not part.is_empty and part.area > 0:
                # 5 m simplification is subpixel at 30 m and only reduces request size.
                part = part.simplify(5.0, preserve_topology=True)
                yield f"{ix}_{iy}", part


def fetch_stats_once(tile_id: str, geometry, variable: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "f": "json",
        "geometry": json.dumps(esri_polygon(geometry), separators=(",", ":")),
        "geometryType": "esriGeometryPolygon",
        "inSR": "5070",
        "pixelSize": json.dumps(
            {"x": PIXEL_M, "y": PIXEL_M},
            separators=(",", ":"),
        ),
    }
    if variable == "slope_pct_rise":
        params["renderingRule"] = json.dumps(SLOPE_RULE, separators=(",", ":"))
    last_error = ""
    for attempt in range(2):
        try:
            response = requests.post(SERVICE, data=params, timeout=(15, 120))
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(json.dumps(payload["error"]))
            statistics = payload.get("statistics") or []
            if not statistics:
                raise RuntimeError("USGS 3DEP returned no statistics for the tile geometry")
            stat = statistics[0]
            count = int(stat.get("count", 0))
            if count <= 0:
                raise RuntimeError("USGS 3DEP returned zero valid cells")
            return {
                "tile_id": tile_id,
                "variable": variable,
                "count": count,
                "minimum": float(stat["min"]),
                "maximum": float(stat["max"]),
                "sum": float(stat.get("sum", float(stat["mean"]) * count)),
                "mean": float(stat["mean"]),
                "intersection_area_sq_m": float(geometry.area),
                "response": payload,
            }
        except Exception as exc:
            last_error = str(exc)
            if "exceeds the size limit" in last_error.lower() or "exceeds size limit" in last_error.lower():
                raise
            if attempt == 0:
                time.sleep(1)
    raise RuntimeError(f"{tile_id} {variable}: {last_error}")


def fetch_stats_adaptive(tile_id: str, geometry, variable: str, depth: int = 0) -> list[dict[str, Any]]:
    try:
        return [fetch_stats_once(tile_id, geometry, variable)]
    except Exception as exc:
        message = str(exc).lower()
        if "exceeds the size limit" not in message and "exceeds size limit" not in message:
            raise
        if depth >= 5:
            raise RuntimeError(f"{tile_id} {variable}: image-size limit persists after 5 levels of subdivision") from exc
        minx, miny, maxx, maxy = geometry.bounds
        midx, midy = (minx + maxx) / 2, (miny + maxy) / 2
        quadrants = (
            box(minx, miny, midx, midy),
            box(midx, miny, maxx, midy),
            box(minx, midy, midx, maxy),
            box(midx, midy, maxx, maxy),
        )
        pieces = []
        for index, quadrant in enumerate(quadrants):
            part = geometry.intersection(quadrant)
            if not part.is_empty and part.area > 0:
                pieces.extend(fetch_stats_adaptive(f"{tile_id}.{index}", part, variable, depth + 1))
        if not pieces:
            raise RuntimeError(f"{tile_id} {variable}: adaptive subdivision produced no valid area") from exc
        return pieces


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations", nargs="+", default=list(STATIONS), choices=STATIONS)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for station_id in args.stations:
        source_path = RAW / f"usgs_nldi_validated_basin_{station_id}.geojson"
        if not source_path.exists():
            raise FileNotFoundError(f"Validated basin missing for {station_id}: {source_path}")
        basin = gpd.read_file(source_path)
        if len(basin) != 1 or basin.crs is None:
            raise ValueError(f"Expected one CRS-defined validated basin for {station_id}")
        if str(basin.iloc[0]["station_id"]) != station_id:
            raise ValueError(f"Validated basin station_id mismatch for {station_id}")
        geom = basin.to_crs("EPSG:5070").geometry.iloc[0]
        tiles = list(tile_geometries(geom))
        raw_record: dict[str, Any] = {
            "station_id": station_id,
            "source_boundary": source_path.name,
            "service": SERVICE,
            "retrieved_date": date.today().isoformat(),
            "output_resolution_m": PIXEL_M,
            "processing_crs": "EPSG:5070",
            "tile_size_m": TILE_M,
            "boundary_simplification_m": 5,
            "aggregation_weight": "EPSG:5070 area of each tile-boundary intersection; valid across 3DEP's multiresolution mosaic",
            "tile_count": len(tiles),
            "complete": False,
            "variables": {},
        }
        station_all_ok = True
        for variable in ("elevation_m", "slope_pct_rise"):
            results: list[dict[str, Any]] = []
            errors: list[str] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(fetch_stats_adaptive, tile_id, geom_part, variable): (tile_id, geom_part.area)
                    for tile_id, geom_part in tiles
                }
                for completed_index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                    try:
                        child_results = future.result()
                        for result in child_results:
                            results.append(result)
                    except Exception as exc:
                        errors.append(str(exc))
                    print(f"{station_id} {variable}: {completed_index}/{len(tiles)} top-level tiles", flush=True)
            results.sort(key=lambda item: item["tile_id"])
            count = sum(item["count"] for item in results)
            weighted_total = sum(item["mean"] * item["intersection_area_sq_m"] for item in results)
            weight_area = sum(item["intersection_area_sq_m"] for item in results)
            summary = {
                "count": count,
                "minimum": min((item["minimum"] for item in results), default=None),
                "maximum": max((item["maximum"] for item in results), default=None),
                "mean": weighted_total / weight_area if weight_area else None,
                "weight_area_sq_m": weight_area,
                "complete": not errors and weight_area > 0 and abs(weight_area - geom.area) / geom.area <= 0.01,
                "errors": errors,
                "tiles": results,
            }
            raw_record["variables"][variable] = summary
            station_all_ok &= bool(summary["complete"])
        raw_record["complete"] = station_all_ok
        output = OUT_DIR / f"usgs_3dep_30m_corrected_{station_id}.json"
        output.write_text(json.dumps(raw_record, indent=2), encoding="utf-8")
        records.append(
            {
                "station_id": station_id,
                "complete": station_all_ok,
                "tile_count": len(tiles),
                "mean_elevation_m": raw_record["variables"]["elevation_m"]["mean"],
                "minimum_elevation_m": raw_record["variables"]["elevation_m"]["minimum"],
                "maximum_elevation_m": raw_record["variables"]["elevation_m"]["maximum"],
                "mean_slope_pct": raw_record["variables"]["slope_pct_rise"]["mean"],
                "source_file": output.name,
            }
        )
        print(json.dumps(records[-1]), flush=True)
    if len(records) != len(args.stations) or any(not row["complete"] for row in records):
        print("WARNING: one or more requested 3DEP station outputs are incomplete; incomplete summaries must not be used.", flush=True)
    (RAW / "usgs_3dep_30m_summary.csv").write_text(
        "station_id,complete,tile_count,mean_elevation_m,minimum_elevation_m,maximum_elevation_m,mean_slope_pct,source_file\n"
        + "".join(
            f"{r['station_id']},{r['complete']},{r['tile_count']},{r['mean_elevation_m']},{r['minimum_elevation_m']},{r['maximum_elevation_m']},{r['mean_slope_pct']},{r['source_file']}\n"
            for r in records
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
