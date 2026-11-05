# Floodcast frontend

Run `npm install`, then `npm run dev` from this directory.

The development server exposes the existing project CSV files through read-only `/workspace-data/*` endpoints. It does not copy source datasets into this directory. The adapter is in `src/services/data.js`; replace its local source calls with the documented `/api/*` routes when the FastAPI service is ready.

Observed discharge, station metadata, NASA POWER weather, processed catchment values, PRISM normals, and Annual NLCD summaries are read from the existing project outputs. Forecasts and model scores remain empty until validated output files or API responses exist. Catchment fields with blank or rejected source results are shown as unavailable.

## Live river monitoring

The monitoring map uses React Leaflet, Leaflet, and OpenStreetMap tiles. It requests the modern USGS Water Data API `latest-continuous` collection for `USGS-01646500`, `USGS-02087500`, `USGS-07010000`, and `USGS-08158000`, with parameter codes `00060` (discharge) and `00065` (gage height). The development proxy in `vite.config.js` avoids browser CORS issues and does not use the deprecated WaterServices endpoints. Production should route live requests through the Floodcast backend.

The live data service is `src/services/liveStations.js`; the app-level polling/cache is `src/hooks/LiveStationsContext.jsx`. It shares one request across the map and monitoring panel, refreshes every five minutes, and keeps the last successful snapshot visible if an update fails. Only continuous USGS measurements appear in the live panel. Existing CSV daily means remain labeled historical. Predictions are displayed only when returned by the predictions API. Risk colors are used only when a station classification includes a threshold source; otherwise markers and labels stay neutral/unavailable.

The backend is not implemented in this project yet. `src/services/api.js` defines the frontend adapter and expected routes:

| Route | Expected response |
| --- | --- |
| `GET /api/stations` | Station metadata array or `{ "stations": [...] }` |
| `GET /api/stations/live` | `{ "stations": [{ "station_id": "01646500", "streamflow": { "value": 123, "time": "ISO-8601", "unit": "ft3/s", "approval_status": "approved", "parameter_code": "00060" }, "gauge_height": { "value": 4.2, "time": "ISO-8601", "unit": "ft", "approval_status": "provisional", "parameter_code": "00065" }, "risk_classification": "moderate", "risk_threshold_source": "..." }], "updated_at": "ISO-8601" }` |
| `GET /api/predictions` | `{ "predictions": [{ "station_id": "01646500", "predicted_discharge": 123, "unit": "ft3/s", "valid_time": "ISO-8601" }] }` |
| `GET /api/stations/{station_id}` | Station metadata and available observations for one station |

Unavailable values should be omitted or `null`. The development USGS adapter is a demonstration fallback only; once backend routes are deployed, set `VITE_API_BASE_URL` if they are hosted on a different origin.
