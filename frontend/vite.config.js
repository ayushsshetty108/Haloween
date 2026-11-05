import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'

// Development-only, read-only access to existing project datasets. Nothing is copied into frontend/.
function workspaceData() {
  const project = path.resolve(process.cwd(), '..')
  const files = {
    catchment: 'data/processed/catchment_characteristics.csv',
    discharge: 'data/processed/usgs_daily_mean.csv',
    stations: 'data/raw/monitoring.csv',
    drainage: 'data/raw/usgs_drainage_areas.csv',
    prism: 'data/raw/prism_ppt_1991_2020_zonal_summary.csv',
    nlcd: 'data/raw/annual_nlcd_2024_zonal_summary.csv',
  }
  return {
    name: 'read-only-workspace-data',
    configureServer(server) {
      server.middlewares.use('/workspace-data', (req, res, next) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') { res.statusCode = 405; res.end('Read-only dataset access'); return }
        const parts = decodeURIComponent(req.url || '').split('/').filter(Boolean)
        let relative = files[parts[0]]
        if (parts[0] === 'weather' && /^\d{8}$/.test(parts[1] || '')) relative = `data/raw/nasa_power_${parts[1]}.csv`
        if (parts[0] === 'boundary' && /^\d{8}$/.test(parts[1] || '')) relative = `data/raw/usgs_nldi_validated_basin_${parts[1]}.geojson`
        const allowedParts = ['weather', 'boundary'].includes(parts[0]) ? 2 : 1
        if (!relative || parts.length > allowedParts) return next()
        if (allowedParts === 2 && parts.length !== 2) return next()
        const file = path.resolve(project, relative)
        if (!file.startsWith(`${project}${path.sep}`) || !fs.existsSync(file)) { res.statusCode = 404; res.end('Dataset unavailable'); return }
        res.setHeader('Access-Control-Allow-Origin', '*')
        res.setHeader('Content-Type', parts[0] === 'boundary' ? 'application/geo+json' : 'text/csv; charset=utf-8')
        fs.createReadStream(file).pipe(res)
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), workspaceData()],
  server: {
    host: '0.0.0.0',
    proxy: {
      // Development-only public USGS proxy; production should use the Floodcast API.
      '/usgs-api': { target: 'https://api.waterdata.usgs.gov', changeOrigin: true, rewrite: path => path.replace(/^\/usgs-api/, '/ogcapi/v1') },
    },
  },
})
