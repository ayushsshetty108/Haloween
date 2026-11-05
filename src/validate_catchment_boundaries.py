"""Audit station identity, outlet placement, and USGS watershed boundaries.

This script validates exact NLDI feature IDs and independently compares saved
StreamStats delineations with NWIS drainage areas. It only writes a
station-specific validated basin when the geometry and area checks pass.
Original downloads are never modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import Geod
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely import make_valid
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REPORTS = ROOT / "reports"
GEOD = Geod(ellps="WGS84")
SQM_PER_SQMI = 2_589_988.110336
NHDPLUS_AREA_TOLERANCE_PCT = 0.1

STATIONS = {
    "01646500": (38.949778, -77.127639),
    "02087500": (35.647222, -78.405278),
    "07010000": (38.629000, -90.179778),
    "08158000": (30.246139, -97.680056),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def geodesic_area_sqmi(geometry) -> float:
    area_m2, _ = GEOD.geometry_area_perimeter(geometry)
    return abs(area_m2) / SQM_PER_SQMI


def valid_polygonal(geometry):
    """Repair invalid input and retain polygon components only."""
    repaired = make_valid(geometry)
    if isinstance(repaired, (Polygon, MultiPolygon)):
        return repaired
    polygons = [part for part in getattr(repaired, "geoms", [])
                if isinstance(part, (Polygon, MultiPolygon))]
    return unary_union(polygons) if polygons else repaired


def parse_nwis() -> pd.DataFrame:
    path = RAW / "usgs_station_verification_nwis.rdb"
    lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines()
             if line and not line.startswith("#")]
    if len(lines) < 3:
        raise ValueError("NWIS RDB is missing its header, type row, or station records")
    return pd.read_csv(pd.io.common.StringIO("\n".join([lines[0], *lines[2:]])),
                       sep="\t", dtype={"site_no": "string"})


def streamstats_records(station_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    paths = [RAW / f"streamstats_ssdelineate_{station_id}.json",
             RAW / f"streamstats_{station_id}.json"]
    for path in paths:
        if not path.exists():
            continue
        document = read_json(path)
        if document.get("type") == "FeatureCollection":
            for feature in document.get("features", []):
                props = feature.get("properties", {})
                geom = shape(feature["geometry"]) if feature.get("geometry") else None
                found.append({
                    "file": path.name,
                    "scope": props.get("scope", ""),
                    "warning": props.get("WarningMsg", ""),
                    "shape_area_attribute": props.get("Shape_Area"),
                    "geometry": geom,
                })
            continue
        request = document.get("bcrequest", {})
        wsresp = request.get("wsresp", {})
        nested = wsresp.get("featurecollection", [])
        for group in nested:
            for named in group:
                feature_collection = named.get("feature", {})
                for feature in feature_collection.get("features", []):
                    props = feature.get("properties", {})
                    geom = shape(feature["geometry"]) if feature.get("geometry") else None
                    found.append({
                        "file": path.name,
                        "scope": named.get("name", ""),
                        "warning": props.get("WarningMsg", ""),
                        "shape_area_attribute": props.get("Shape_Area"),
                        "geometry": geom,
                    })
    return found


def streamstats_summary(station_id: str) -> tuple[float | None, str, bool, Any]:
    records = streamstats_records(station_id)
    candidate = next((r for r in records if r["scope"] == "globalwatershed" and r["geometry"]), None)
    if candidate is None:
        candidate = next((r for r in records if r["scope"] == "upstream_basin" and r["geometry"]), None)
    if candidate is None:
        return None, "No nonempty upstream watershed geometry in saved StreamStats response", False, None
    area = geodesic_area_sqmi(candidate["geometry"])
    warnings = [r["warning"] for r in records if r["warning"]]
    if warnings:
        return area, "; ".join(dict.fromkeys(warnings)), False, candidate["geometry"]
    if area < 1.0:
        return area, "Saved response contains only a local cell-sized polygon", False, candidate["geometry"]
    return area, "No StreamStats warning; polygon returned", True, candidate["geometry"]


def main() -> None:
    nwis = parse_nwis().set_index("site_no", drop=False)
    existing_areas = pd.read_csv(RAW / "usgs_drainage_areas.csv", dtype={"station_id": "string"})
    existing_areas = existing_areas.set_index("station_id", drop=False)
    records: list[dict[str, Any]] = []
    basin_out = RAW / "usgs_nldi_validated_basin_{station_id}.geojson"

    for station_id, expected_xy in STATIONS.items():
        if station_id not in nwis.index or station_id not in existing_areas.index:
            raise ValueError(f"Station {station_id} is missing from NWIS or project drainage data")
        nwis_row = nwis.loc[station_id]
        lat, lon = float(nwis_row["dec_lat_va"]), float(nwis_row["dec_long_va"])
        coord_ok = abs(lat - expected_xy[0]) <= 0.00005 and abs(lon - expected_xy[1]) <= 0.00005
        total = float(nwis_row["drain_area_va"])
        contributing = pd.to_numeric(nwis_row["contrib_drain_area_va"], errors="coerce")
        project_total = float(existing_areas.loc[station_id, "drainage_area_sq_mi"])
        existing_contrib = pd.to_numeric(
            existing_areas.loc[station_id, "contributing_drainage_area_sq_mi"], errors="coerce"
        )
        if abs(project_total - total) > 0.01:
            raise ValueError(f"Existing total area does not match NWIS for {station_id}")
        if pd.notna(contributing) != pd.notna(existing_contrib) or (
            pd.notna(contributing) and abs(float(contributing) - float(existing_contrib)) > 0.01
        ):
            raise ValueError(f"Existing contributing area does not match NWIS for {station_id}")

        station_doc = read_json(RAW / f"usgs_nldi_station_{station_id}.geojson")
        if len(station_doc.get("features", [])) != 1:
            raise ValueError(f"NLDI did not return exactly one station feature for {station_id}")
        station_feature = station_doc["features"][0]
        station_props = station_feature["properties"]
        expected_identifier = f"USGS-{station_id}"
        if station_props.get("identifier") != expected_identifier:
            raise ValueError(f"NLDI station identifier mismatch for {station_id}")
        comid = int(station_props["comid"])
        station_geom = shape(station_feature["geometry"])
        station_xy = station_geom.coords[0]
        station_coord_ok = abs(station_xy[1] - lat) < 1e-6 and abs(station_xy[0] - lon) < 1e-6

        flow_doc = read_json(RAW / f"usgs_nhdplus_flowline_{station_id}.geojson")
        if len(flow_doc.get("features", [])) != 1:
            raise ValueError(f"Expected one NHDPlus flowline feature for {station_id}")
        flow = flow_doc["features"][0]
        flow_props = flow["properties"]
        if int(flow_props["comid"]) != comid:
            raise ValueError(f"NHDPlus flowline COMID does not match NLDI station for {station_id}")
        nhd_area = float(flow_props["totdasqkm"]) / 2.589988110336

        basin_doc = read_json(RAW / f"usgs_nldi_basin_{station_id}.geojson")
        if len(basin_doc.get("features", [])) != 1:
            raise ValueError(f"Expected one NLDI basin feature for {station_id}")
        basin_feature = basin_doc["features"][0]
        basin_original = shape(basin_feature["geometry"])
        basin_geom = valid_polygonal(basin_original)
        basin_area = geodesic_area_sqmi(basin_geom)

        split_path = RAW / f"usgs_nldi_splitcatchment_{station_id}.geojson"
        split_doc = read_json(split_path) if split_path.exists() else {"features": []}
        split_features = {f.get("id"): f for f in split_doc.get("features", [])}
        catchment_feature = split_features.get("catchment")
        split_feature = split_features.get("splitCatchment")
        split_original = shape(split_feature["geometry"]) if split_feature and split_feature.get("geometry") else None
        local_original = shape(catchment_feature["geometry"]) if catchment_feature and catchment_feature.get("geometry") else None
        split_geom = valid_polygonal(split_original) if split_original else None
        local_geom = valid_polygonal(local_original) if local_original else None
        local_comid = int(catchment_feature["properties"].get("catchmentID", -1)) if catchment_feature else None

        local_area = geodesic_area_sqmi(local_geom) if local_geom else None
        split_area = geodesic_area_sqmi(split_geom) if split_geom else None
        local_valid = bool(local_geom and local_geom.is_valid and local_comid == comid)
        split_valid = bool(split_geom and split_geom.is_valid and local_geom and local_geom.buffer(1e-9).covers(split_geom))
        basin_local_outside_sqkm = None
        basin_covers_local = False
        if local_geom and basin_geom and basin_geom.is_valid:
            local_projected = gpd.GeoSeries([local_geom], crs="EPSG:4326").to_crs("EPSG:5070").iloc[0]
            basin_projected = gpd.GeoSeries([basin_geom], crs="EPSG:4326").to_crs("EPSG:5070").iloc[0]
            local_area_sqkm = local_projected.area / 1_000_000.0
            basin_local_outside_sqkm = local_projected.difference(basin_projected).area / 1_000_000.0
            # Small sliver differences can occur because the core basin and split
            # process serve NHDPlus geometries at slightly different precision.
            basin_covers_local = basin_local_outside_sqkm <= max(local_area_sqkm * 0.001, 1e-5)

        corrected_geom = None
        corrected_area = None
        if local_valid and split_valid and basin_covers_local:
            corrected_geom = basin_geom.difference(local_geom).union(split_geom)
            if not corrected_geom.is_valid:
                corrected_geom = corrected_geom.buffer(0)
            corrected_area = geodesic_area_sqmi(corrected_geom)

        nldi_delta = (basin_area - total) / total * 100.0
        corrected_delta = ((corrected_area - total) / total * 100.0) if corrected_area is not None else None
        corrected_nhd_delta = ((corrected_area - nhd_area) / nhd_area * 100.0) if corrected_area is not None else None
        streamstats_area, streamstats_note, streamstats_valid, streamstats_geom = streamstats_summary(station_id)
        streamstats_delta = ((streamstats_area - total) / total * 100.0) if streamstats_area is not None else None
        streamstats_overlap_pct = None
        if streamstats_valid and corrected_geom is not None and streamstats_geom is not None:
            nldi_projected = gpd.GeoSeries([corrected_geom], crs="EPSG:4326").to_crs("EPSG:5070").iloc[0]
            stream_projected = gpd.GeoSeries([streamstats_geom], crs="EPSG:4326").to_crs("EPSG:5070").iloc[0]
            streamstats_overlap_pct = 100.0 * nldi_projected.intersection(stream_projected).area / nldi_projected.union(stream_projected).area

        reasons = []
        if not coord_ok or not station_coord_ok:
            reasons.append("NWIS/NLDI station coordinate mismatch")
        if not (local_valid and split_valid and basin_covers_local and corrected_geom and corrected_geom.is_valid):
            reasons.append("exact local split or full basin containment failed validation")
        if corrected_nhd_delta is None or abs(corrected_nhd_delta) > NHDPLUS_AREA_TOLERANCE_PCT:
            reasons.append(f"corrected NLDI basin area differs from matched NHDPlus TotDASqKm by {corrected_nhd_delta:.3f}%" if corrected_nhd_delta is not None else "no corrected basin geometry")
        elif corrected_delta is not None and abs(corrected_delta) > 1.0:
            reasons.append(f"accepted NHDPlus-consistent boundary; NWIS total area discrepancy flagged at {corrected_delta:.2f}%")
        if streamstats_valid:
            if streamstats_overlap_pct is not None:
                reasons.append(f"independent StreamStats basin overlap is {streamstats_overlap_pct:.2f}%")
            else:
                reasons.append("independent StreamStats delineation available for comparison")
        else:
            reasons.append(f"StreamStats not usable: {streamstats_note}")

        selected = bool(coord_ok and station_coord_ok and local_valid and split_valid and basin_covers_local
                        and corrected_geom and corrected_geom.is_valid and corrected_nhd_delta is not None
                        and abs(corrected_nhd_delta) <= NHDPLUS_AREA_TOLERANCE_PCT)
        decision = ("ACCEPTED; NWIS AREA DISCREPANCY FLAGGED" if selected and corrected_delta is not None and abs(corrected_delta) > 1.0
                    else "ACCEPTED" if selected else "UNRESOLVED; do not calculate new features")
        if selected:
            output_path = Path(str(basin_out).format(station_id=station_id))
            feature = {
                "type": "Feature",
                "geometry": mapping(corrected_geom),
                "properties": {
                    "station_id": station_id,
                    "nldi_identifier": expected_identifier,
                    "nldiplus_comid": comid,
                    "boundary_method": "NLDI upstream basin minus full COMID local catchment plus upstream split at station coordinate",
                    "nwis_total_area_sq_mi": total,
                    "nhdplus_totdasqkm_area_sq_mi": nhd_area,
                    "corrected_polygon_area_sq_mi": corrected_area,
                    "area_difference_pct_vs_nwis": corrected_delta,
                    "area_difference_pct_vs_nhdplus": corrected_nhd_delta,
                },
            }
            output_path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}, indent=2), encoding="utf-8")

        records.append({
            "station_id": station_id,
            "nwis_station_name": str(nwis_row["station_nm"]),
            "nwis_total_area_sq_mi": total,
            "nwis_contributing_area_sq_mi": float(contributing) if pd.notna(contributing) else None,
            "project_area_matches_nwis": abs(project_total - total) <= 0.01,
            "nwis_coordinates_match_requested": coord_ok,
            "nldi_identifier": station_props.get("identifier"),
            "nldi_comid": comid,
            "nldi_reachcode": station_props.get("reachcode"),
            "nldi_measure": station_props.get("measure"),
            "nldi_point_matches_nwis_coordinates": station_coord_ok,
            "local_catchment_comid_matches": local_comid == comid,
            "nldi_basin_area_sq_mi": round(basin_area, 2),
            "nldi_source_geometry_valid": bool(basin_original.is_valid),
            "nldi_geometry_repaired": not basin_original.is_valid,
            "nldi_area_difference_pct_vs_nwis": round(nldi_delta, 3),
            "local_catchment_area_sq_mi": round(local_area, 4) if local_area is not None else None,
            "local_catchment_outside_full_basin_sqkm": round(basin_local_outside_sqkm, 8) if basin_local_outside_sqkm is not None else None,
            "upstream_split_area_sq_mi": round(split_area, 4) if split_area is not None else None,
            "corrected_basin_area_sq_mi": round(corrected_area, 2) if corrected_area is not None else None,
            "corrected_area_difference_pct_vs_nwis": round(corrected_delta, 3) if corrected_delta is not None else None,
            "nhdplus_totdasqkm_area_sq_mi": round(nhd_area, 2),
            "corrected_area_difference_pct_vs_nhdplus": round(corrected_nhd_delta, 4) if corrected_nhd_delta is not None else None,
            "nhdplus_area_difference_pct_vs_nwis": round((nhd_area - total) / total * 100, 3),
            "streamstats_area_sq_mi": round(streamstats_area, 6) if streamstats_area is not None else None,
            "streamstats_boundary_overlap_pct": round(streamstats_overlap_pct, 2) if streamstats_overlap_pct is not None else None,
            "streamstats_area_difference_pct_vs_nwis": round(streamstats_delta, 3) if streamstats_delta is not None else None,
            "streamstats_status": streamstats_note,
            "selected_boundary": "corrected NLDI split basin" if selected else "",
            "boundary_decision": decision,
            "decision_reason": "; ".join(reasons),
        })

    result = pd.DataFrame(records)
    REPORTS.mkdir(parents=True, exist_ok=True)
    result.to_csv(REPORTS / "catchment_boundary_validation.csv", index=False, na_rep="")
    lines = [
        "# Catchment boundary validation",
        "",
        "Validation date: 2026-11-05.",
        "",
        "## Criteria",
        "",
        "Station identity is joined by exact NWIS site number. NLDI station identifier, COMID, NHDPlus flowline COMID, and split-process local catchment COMID must agree. The station coordinate must match the requested/NWIS coordinate. Invalid source polygons are repaired with Shapely make_valid and flagged. The split local catchment must match the COMID, and the upstream split must be valid and contained in it. Local catchment containment allows at most 0.1% of its area outside the full basin because the services return slightly different edge precision. A corrected basin is formed as (NLDI basin − full local catchment) ∪ upstream split polygon. It is accepted for extraction only if valid and its geodesic area agrees with the matched NHDPlus flowline TotDASqKm within 0.1%. NWIS total/contributing area remains an independent check; conflicts are flagged, never silently adjusted. StreamStats is an independent cross-check only when the returned basin has no not-snappable warning and is not cell-sized.",
        "",
        "## Results",
        "",
        "| Station | NWIS total (sq mi) | NHDPlus TotDA (sq mi) | Corrected split (sq mi) | Δ vs NHDPlus | Δ vs NWIS | StreamStats (sq mi) | Decision |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in records:
        corr = f"{row['corrected_basin_area_sq_mi']:.2f}" if row["corrected_basin_area_sq_mi"] is not None else "blank"
        delta = f"{row['corrected_area_difference_pct_vs_nwis']:.3f}%" if row["corrected_area_difference_pct_vs_nwis"] is not None else "blank"
        nhd_delta = f"{row['corrected_area_difference_pct_vs_nhdplus']:.4f}%" if row["corrected_area_difference_pct_vs_nhdplus"] is not None else "blank"
        unusable = "unusable" in row["streamstats_status"].lower() or "snappable" in row["streamstats_status"].lower() or "cell-sized" in row["streamstats_status"].lower()
        ss = f"{row['streamstats_area_sq_mi']:.6f} (invalid)" if row["streamstats_area_sq_mi"] is not None and unusable else (f"{row['streamstats_area_sq_mi']:.2f}" if row["streamstats_area_sq_mi"] is not None else "blank")
        lines.append(f"| {row['station_id']} | {row['nwis_total_area_sq_mi']:.0f} | {row['nhdplus_totdasqkm_area_sq_mi']:.2f} | {corr} | {nhd_delta} | {delta} | {ss} | {row['boundary_decision']} |")
    lines.extend(["", "## Station-by-station findings", ""])
    for row in records:
        lines.append(f"- **{row['station_id']}** — COMID {row['nldi_comid']}, reach {row['nldi_reachcode']}, measure {row['nldi_measure']}; local catchment {row['local_catchment_area_sq_mi']} sq mi; split upstream portion {row['upstream_split_area_sq_mi']} sq mi. {row['boundary_decision']}: {row['decision_reason']}.")
    lines.extend([
        "",
        "## StreamStats file audit",
        "",
        "All saved `streamstats_ssdelineate_*.json` files were parsed. The North Carolina response for 02087500 has no not-snappable warning and contains a full watershed polygon. The Maryland, Missouri, and Texas responses report a not-snappable warning and return cell-sized polygons. The legacy `streamstats_08158000.json` contains a 45 m² split cell and an empty upstream basin, so it is not a watershed boundary. No `usgs_nldi_flowline_*.geojson` files were present; the project instead has USGS Hydrologic Fabric/NHDPlus flowline records named `usgs_nhdplus_flowline_*.geojson`.",
        "",
        "Raw NLDI, StreamStats, NWIS, and NHDPlus records were left intact. A `usgs_nldi_validated_basin_{station_id}.geojson` is created only for accepted stations. The NHDPlus area comparison is an internal consistency check, not independent confirmation of USGS NWIS area; large NWIS conflicts require user awareness and are retained as limitations.",
    ])
    (REPORTS / "catchment_boundary_validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result[["station_id", "nldi_basin_area_sq_mi", "corrected_basin_area_sq_mi", "corrected_area_difference_pct_vs_nwis", "streamstats_area_sq_mi", "boundary_decision"]].to_string(index=False))


if __name__ == "__main__":
    main()
