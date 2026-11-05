const STATION_META = [
  { id: '01646500', river: 'Potomac River', name: 'Little Falls', state: 'Maryland' },
  { id: '02087500', river: 'Neuse River', name: 'Near Clayton', state: 'North Carolina' },
  { id: '07010000', river: 'Mississippi River', name: 'At St. Louis', state: 'Missouri' },
  { id: '08158000', river: 'Colorado River', name: 'At Austin', state: 'Texas' },
]

const csvRows = (text) => {
  const rows = []; let row = []; let value = ''; let quoted = false
  for (let i=0;i<text.length;i++) {
    const c=text[i]
    if(c==='"'&&text[i+1]==='"'&&quoted){value+='"';i++}
    else if(c==='"') quoted=!quoted
    else if(c===','&&!quoted){row.push(value);value=''}
    else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(value);if(row.some(cell=>cell!==''))rows.push(row);row=[];value=''}
    else value+=c
  }
  if(value!==''||row.length){row.push(value);rows.push(row)}
  const headers = rows.shift() || []
  return rows.map(cells => Object.fromEntries(headers.map((header,i)=>[header,cells[i]??''])))
}
const number = value => value === '' || value == null || value === '-999' ? null : Number.isFinite(Number(value)) ? Number(value) : null
const getText = async (route) => { const response = await fetch(`/workspace-data/${route}`); if (!response.ok) throw new Error(`Local dataset unavailable (${route})`); return response.text() }
const cache = new Map()
const cached = (key, loader) => { if (!cache.has(key)) cache.set(key, loader()); return cache.get(key) }

async function all() {
  const [sites, areas, catchment, discharge, prism, nlcd] = await Promise.all([
    getText('stations').then(csvRows), getText('drainage').then(csvRows), getText('catchment').then(csvRows),
    getText('discharge').then(csvRows), getText('prism').then(csvRows), getText('nlcd').then(csvRows),
  ])
  const siteById = new Map(sites.map(row => [row.monitoring_location_number, row]))
  const areaById = new Map(areas.map(row => [row.station_id, row]))
  const catchById = new Map(catchment.map(row => [row.station_id, row]))
  const prismById = new Map(prism.map(row => [row.station_id, row]))
  const nlcdById = new Map(nlcd.map(row => [row.station_id, row]))
  const flowById = new Map(STATION_META.map(s => [s.id, []]))
  for (const row of discharge) {
    const id = (row.monitoring_location_id || '').replace('USGS-', '')
    const value = number(row.value)
    if (flowById.has(id) && value != null) flowById.get(id).push({ date: row.time, discharge: value })
  }
  for (const values of flowById.values()) values.sort((a,b)=>a.date.localeCompare(b.date))
  const stations = STATION_META.map(meta => {
    const site = siteById.get(meta.id) || {}
    const stats = catchById.get(meta.id) || {}
    const flows = flowById.get(meta.id) || []
    return { ...meta, latitude: number(site.y), longitude: number(site.x), discharge: flows, latest: flows.at(-1) || null,
      records: flows.length, drainageArea: number(stats.drainage_area_sq_mi), elevation: number(stats.mean_elevation_m), slope: number(stats.mean_slope_pct),
      forest: number(stats.forest_cover_pct), impervious: number(stats.impervious_cover_pct), urban: number(stats.urban_cover_pct), wetlands: number(stats.wetland_cover_pct),
      precipitation: number((prismById.get(meta.id) || {}).mean_annual_precipitation_mm ?? stats.mean_annual_precipitation_mm),
      precipitationSource: prismById.has(meta.id) ? 'PRISM 1991–2020' : 'Catchment output',
      soil: { a: number(stats.soil_group_a_pct), b: number(stats.soil_group_b_pct), c: number(stats.soil_group_c_pct), d: number(stats.soil_group_d_pct), awc: number(stats.available_water_capacity), conductivity: number(stats.saturated_hydraulic_conductivity) },
      nlcdComplete: (nlcdById.get(meta.id) || {}).complete === 'True',
      contributingArea: number((areaById.get(meta.id) || {}).contributing_drainage_area_sq_mi),
    }
  })
  return { stations, totalRecords: stations.reduce((sum,s)=>sum+s.records,0) }
}

export const getOverview = () => cached('all', all)
export const getStations = async () => (await getOverview()).stations
export const getStation = async (id) => (await getStations()).find(station => station.id === id) || null
export const getWeather = (id) => cached(`weather-${id}`, async () => {
  const text = await getText(`weather/${id}`)
  const lines = text.split(/\r?\n/); const start = lines.findIndex(line => line.startsWith('YEAR,DOY,'))
  if (start < 0) return []
  const rows = csvRows(lines.slice(start).join('\n'))
  return rows.map(row => {
    const year = Number(row.YEAR), doy = Number(row.DOY), date = new Date(Date.UTC(year,0,doy))
    return { date: date.toISOString().slice(0,10), precipitation: number(row.PRECTOTCORR), maxTemp: number(row.T2M_MAX), minTemp: number(row.T2M_MIN), soilMoisture: number(row.GWETTOP) }
  })
})
export const getBoundary = (id) => cached(`boundary-${id}`, async () => {
  const response = await fetch(`/workspace-data/boundary/${id}`)
  if (!response.ok) throw new Error('Verified basin boundary could not be loaded.')
  return response.json()
})
export const getPredictions = async () => { throw new Error('No validated prediction output is available yet.') }
export const getModelPerformance = async () => { throw new Error('No model validation results are available yet.') }
export const API_PATHS = { overview: '/api/overview', stations: '/api/stations', discharge: '/api/discharge', weather: '/api/weather', catchment: '/api/catchment', predictions: '/api/predictions', modelPerformance: '/api/model-performance' }
