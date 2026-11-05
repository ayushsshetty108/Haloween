# Catchment boundary validation

Validation date: 2026-11-05.

## Criteria

Station identity is joined by exact NWIS site number. NLDI station identifier, COMID, NHDPlus flowline COMID, and split-process local catchment COMID must agree. The station coordinate must match the requested/NWIS coordinate. Invalid source polygons are repaired with Shapely make_valid and flagged. The split local catchment must match the COMID, and the upstream split must be valid and contained in it. Local catchment containment allows at most 0.1% of its area outside the full basin because the services return slightly different edge precision. A corrected basin is formed as (NLDI basin − full local catchment) ∪ upstream split polygon. It is accepted for extraction only if valid and its geodesic area agrees with the matched NHDPlus flowline TotDASqKm within 0.1%. NWIS total/contributing area remains an independent check; conflicts are flagged, never silently adjusted. StreamStats is an independent cross-check only when the returned basin has no not-snappable warning and is not cell-sized.

## Results

| Station | NWIS total (sq mi) | NHDPlus TotDA (sq mi) | Corrected split (sq mi) | Δ vs NHDPlus | Δ vs NWIS | StreamStats (sq mi) | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| 01646500 | 11560 | 11562.64 | 11561.75 | -0.0077% | 0.015% | 0.000077 (invalid) | ACCEPTED |
| 02087500 | 1150 | 1153.76 | 1153.44 | -0.0286% | 0.299% | 1153.18 | ACCEPTED |
| 07010000 | 697000 | 667324.34 | 667297.09 | -0.0041% | -4.262% | 0.000039 (invalid) | ACCEPTED; NWIS AREA DISCREPANCY FLAGGED |
| 08158000 | 39009 | 34710.30 | 34708.05 | -0.0065% | -11.026% | 0.000017 (invalid) | ACCEPTED; NWIS AREA DISCREPANCY FLAGGED |

## Station-by-station findings

- **01646500** — COMID 4512772, reach 02070008001579, measure 31.913; local catchment 0.917 sq mi; split upstream portion 0.0111 sq mi. ACCEPTED: StreamStats not usable: , Point not snappable using ss-pourpoint API service; results may be inaccurate..
- **02087500** — COMID 8786017, reach 03020201000211, measure 68.544; local catchment 0.3395 sq mi; split upstream portion 0.0003 sq mi. ACCEPTED: independent StreamStats basin overlap is 99.64%.
- **07010000** — COMID 3624735, reach 07140101000028, measure 85.211; local catchment 27.3487 sq mi; split upstream portion 0.0066 sq mi. ACCEPTED; NWIS AREA DISCREPANCY FLAGGED: accepted NHDPlus-consistent boundary; NWIS total area discrepancy flagged at -4.26%; StreamStats not usable: , Point not snappable using ss-pourpoint API service; results may be inaccurate..
- **08158000** — COMID 5781917, reach 12090205000014, measure 40.8832; local catchment 2.2705 sq mi; split upstream portion 0.0007 sq mi. ACCEPTED; NWIS AREA DISCREPANCY FLAGGED: accepted NHDPlus-consistent boundary; NWIS total area discrepancy flagged at -11.03%; StreamStats not usable: , Point not snappable using ss-pourpoint API service; results may be inaccurate..

## StreamStats file audit

All saved `streamstats_ssdelineate_*.json` files were parsed. The North Carolina response for 02087500 has no not-snappable warning and contains a full watershed polygon. The Maryland, Missouri, and Texas responses report a not-snappable warning and return cell-sized polygons. The legacy `streamstats_08158000.json` contains a 45 m² split cell and an empty upstream basin, so it is not a watershed boundary. No `usgs_nldi_flowline_*.geojson` files were present; the project instead has USGS Hydrologic Fabric/NHDPlus flowline records named `usgs_nhdplus_flowline_*.geojson`.

Raw NLDI, StreamStats, NWIS, and NHDPlus records were left intact. A `usgs_nldi_validated_basin_{station_id}.geojson` is created only for accepted stations. The NHDPlus area comparison is an internal consistency check, not independent confirmation of USGS NWIS area; large NWIS conflicts require user awareness and are retained as limitations.
