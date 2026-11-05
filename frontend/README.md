# Floodcast frontend

Run `npm install`, then `npm run dev` from this directory.

The development server exposes the existing project CSV files through read-only `/workspace-data/*` endpoints. It does not copy source datasets into this directory. The adapter is in `src/services/data.js`; replace its local source calls with the documented `/api/*` routes when the FastAPI service is ready.

Observed discharge, station metadata, NASA POWER weather, processed catchment values, PRISM normals, and Annual NLCD summaries are read from the existing project outputs. Forecasts and model scores remain empty until validated output files or API responses exist. Catchment fields with blank or rejected source results are shown as unavailable.
