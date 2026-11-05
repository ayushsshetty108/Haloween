"""Area-weight PRISM 1991–2020 annual precipitation grid over exact basin polygons."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from pyproj import Transformer
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform
from shapely.prepared import prep


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ZIP = RAW / "prism_ppt_1991_2020_m3_4km_annual_bil.zip"
RASTER_NAME = "PRISM_ppt_30yr_normal_4kmM3_annual_bil.bil"
STATIONS = ("01646500", "02087500", "07010000", "08158000")


def main() -> None:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    results = []
    raster_uri = f"zip://{ZIP.resolve().as_posix()}!/{RASTER_NAME}"
    with rasterio.open(raster_uri) as src:
        if src.nodata is None:
            raise ValueError("PRISM raster has no declared NoData value")
        for station_id in STATIONS:
            path = RAW / f"usgs_nldi_validated_basin_{station_id}.geojson"
            features = json.loads(path.read_text(encoding="utf-8"))["features"]
            if len(features) != 1 or str(features[0]["properties"].get("station_id")) != station_id:
                raise ValueError(f"Boundary identity mismatch for {station_id}")
            basin_ll = shape(features[0]["geometry"])
            basin_area = transform(transformer.transform, basin_ll)
            prepared_basin = prep(basin_area)
            masked, affine = mask(src, [mapping(basin_ll)], crop=True, all_touched=True, filled=False)
            values = np.ma.getdata(masked[0])
            source_mask = np.ma.getmaskarray(masked[0])
            total_weighted = 0.0
            total_area = 0.0
            cells = 0
            for row, col in zip(*np.where(~source_mask)):
                value = float(values[row, col])
                if not np.isfinite(value) or value == src.nodata:
                    continue
                x_left, y_top = affine * (int(col), int(row))
                x_right, y_bottom = affine * (int(col) + 1, int(row) + 1)
                cell_ll = Polygon(
                    [(x_left, y_top), (x_right, y_top), (x_right, y_bottom), (x_left, y_bottom), (x_left, y_top)]
                )
                cell_m = transform(transformer.transform, cell_ll)
                if prepared_basin.covers(cell_m):
                    area = cell_m.area
                elif prepared_basin.intersects(cell_m):
                    area = basin_area.intersection(cell_m).area
                else:
                    area = 0.0
                if area > 0:
                    total_weighted += value * area
                    total_area += area
                    cells += 1
            if total_area <= 0:
                raise ValueError(f"No valid PRISM cells intersect basin {station_id}")
            result = {
                "station_id": station_id,
                "mean_annual_precipitation_mm": total_weighted / total_area,
                "weighted_valid_area_sq_km": total_area / 1_000_000.0,
                "valid_grid_cells_intersecting": cells,
                "grid_resolution": "2.5 arc-minute (~4 km)",
                "grid_crs": src.crs.to_string(),
                "period": "1991-2020",
                "dataset_version": "M3; PRISM dataset type an81/r2103h; created 2021-10-29",
                "weighting": "Exact area of each valid PRISM grid-cell polygon intersecting the basin, calculated after transformation to EPSG:5070; cells are area weighted by fractional overlap.",
                "boundary_file": path.name,
                "source_raster_url": "https://prism.oregonstate.edu/request/normals/1991-2020_M3/4km/ppt/PRISM_ppt_30yr_normal_4kmM3_annual_bil.zip",
                "retrieved_date": date.today().isoformat(),
            }
            out_path = RAW / f"prism_ppt_1991_2020_zonal_{station_id}.json"
            out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            results.append(result)
            print(json.dumps({"station_id": station_id, "mean_mm": result["mean_annual_precipitation_mm"], "cells": cells}), flush=True)
    import pandas as pd
    pd.DataFrame(results).to_csv(RAW / "prism_ppt_1991_2020_zonal_summary.csv", index=False)


if __name__ == "__main__":
    main()
