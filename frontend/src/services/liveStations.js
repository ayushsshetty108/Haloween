import { getApiLiveStations, getApiPredictions } from './api.js'

export const USGS_LATEST_CONTINUOUS = 'https://api.waterdata.usgs.gov/ogcapi/v1/collections/latest-continuous/items'
export const LIVE_REFRESH_MS = 5 * 60 * 1000
export const USGS_STATION_IDS = ['01646500', '02087500', '07010000', '08158000']
const USGS_LOCATION_IDS = USGS_STATION_IDS.map(id => `USGS-${id}`)
const CACHE_TTL_MS = 4.5 * 60 * 1000

let liveCache = null
let inFlight = null

function approvalStatus(properties) {
  const value = properties.approval_status ?? properties.approvals_status ?? properties.approvalStatus
  return Array.isArray(value) ? value.join(', ') : value || null
}

function measurement(properties) {
  return {
    value: properties.value == null || properties.value === '' ? null : Number(properties.value),
    time: properties.time ?? properties.observation_time ?? properties.date_time ?? null,
    unit: properties.unit_of_measure ?? properties.unit ?? null,
    approvalStatus: approvalStatus(properties),
    lastModified: properties.last_modified ?? properties.lastModified ?? null,
    parameterCode: String(properties.parameter_code ?? properties.parameterCode ?? ''),
    timeSeriesId: properties.time_series_id ?? properties.timeseries_id ?? null,
  }
}

const later = (next, current) => !current || (Date.parse(next?.time || '') || 0) > (Date.parse(current.time || '') || 0)

function normalizeStationFeatureRows(collection) {
  const stations = Object.fromEntries(USGS_STATION_IDS.map(id => [id, { stationId: id, streamflow: null, gaugeHeight: null, risk: null, prediction: null }]))
  for (const feature of collection?.features || []) {
    const properties = feature.properties || feature
    const stationId = String(properties.monitoring_location_id ?? properties.monitoringLocationId ?? '').replace(/^USGS-/, '')
    const parameterCode = String(properties.parameter_code ?? properties.parameterCode ?? '')
    const row = stations[stationId]
    if (!row || !['00060', '00065'].includes(parameterCode)) continue
    const item = measurement({ ...properties, parameter_code: parameterCode })
    const key = parameterCode === '00060' ? 'streamflow' : 'gaugeHeight'
    if (item.value != null && Number.isFinite(item.value) && later(item, row[key])) row[key] = item
  }
  return Object.values(stations)
}

function normalizeBackendRows(payload) {
  const sourceRows = Array.isArray(payload) ? payload : payload?.stations || payload?.results || []
  const indexed = new Map(sourceRows.map(row => [String(row.station_id ?? row.stationId ?? row.monitoring_location_id ?? '').replace(/^USGS-/, ''), row]))
  return USGS_STATION_IDS.map(stationId => {
    const raw = indexed.get(stationId) || {}
    const streamflow = raw.streamflow || raw.discharge || null
    const gaugeHeight = raw.gauge_height || raw.gaugeHeight || null
    const riskClass = raw.risk_classification ?? raw.risk?.classification ?? null
    const thresholdSource = raw.risk_threshold_source ?? raw.risk?.threshold_source ?? null
    return {
      stationId,
      streamflow: streamflow ? measurement({ ...streamflow, parameter_code: streamflow.parameter_code || '00060' }) : null,
      gaugeHeight: gaugeHeight ? measurement({ ...gaugeHeight, parameter_code: gaugeHeight.parameter_code || '00065' }) : null,
      risk: riskClass && thresholdSource ? { classification: String(riskClass).toLowerCase(), thresholdSource } : null,
      prediction: raw.prediction || null,
    }
  })
}

async function getPublicUsgsMeasurements(signal) {
  const url = new URL(USGS_LATEST_CONTINUOUS)
  url.searchParams.set('f', 'json')
  url.searchParams.set('monitoring_location_id', USGS_LOCATION_IDS.join(','))
  url.searchParams.set('parameter_code', '00060,00065')
  url.searchParams.set('limit', '100')
  const response = await fetch(`/usgs-api${url.pathname.replace('/ogcapi/v1', '')}${url.search}`, { headers: { Accept: 'application/geo+json, application/json' }, signal })
  if (!response.ok) throw new Error(`USGS latest-continuous returned ${response.status}`)
  const data = await response.json()
  return { stations: normalizeStationFeatureRows(data), updatedAt: data.timeStamp || data.timestamp || null }
}

export async function fetchLiveStationSnapshot({ signal, force = false } = {}) {
  if (!force && liveCache && Date.now() - liveCache.cachedAt < CACHE_TTL_MS) return liveCache.snapshot
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const payload = await getApiLiveStations({ signal })
      const [stations, predictionsResult] = await Promise.all([
        Promise.resolve(normalizeBackendRows(payload)),
        getApiPredictions({ signal }).then(value => ({ value })).catch(() => ({ value: null })),
      ])
      const predictionRows = Array.isArray(predictionsResult.value) ? predictionsResult.value : predictionsResult.value?.predictions || []
      const predictionById = new Map(predictionRows.map(row => [String(row.station_id ?? row.stationId ?? '').replace(/^USGS-/, ''), row]))
      for (const station of stations) station.prediction ||= predictionById.get(station.stationId) || null
      const snapshot = { stations, source: 'Floodcast backend', backendConnected: true, updatedAt: payload.updated_at || payload.updatedAt || new Date().toISOString(), fetchedAt: new Date().toISOString() }
      liveCache = { snapshot, cachedAt: Date.now() }
      return snapshot
    } catch (backendError) {
      if (!import.meta.env?.DEV) throw new Error('Live readings are waiting for the Floodcast backend at /api/stations/live.')
      try {
        const publicData = await getPublicUsgsMeasurements(signal)
        const snapshot = { ...publicData, source: 'USGS Water Data API · development proxy', backendConnected: false, backendMessage: 'Floodcast backend is not connected; using the public USGS feed in development.', fetchedAt: new Date().toISOString() }
        liveCache = { snapshot, cachedAt: Date.now() }
        return snapshot
      } catch (usgsError) {
        throw new Error(`Live feed unavailable. Backend: ${backendError.message}. USGS: ${usgsError.message}.`)
      }
    } finally { inFlight = null }
  })()
  return inFlight
}

export function liveFreshness(measurementValue, now = Date.now()) {
  if (!measurementValue?.time) return { label: 'Observation time unavailable', stale: true }
  const ageMs = now - Date.parse(measurementValue.time)
  if (!Number.isFinite(ageMs)) return { label: 'Observation time unavailable', stale: true }
  const minutes = Math.max(0, Math.floor(ageMs / 60000))
  if (minutes <= 30) return { label: minutes < 1 ? 'Observed just now' : `Observed ${minutes} min ago`, stale: false }
  if (minutes < 60) return { label: `Observation is ${minutes} min old`, stale: true }
  const hours = Math.floor(minutes / 60)
  return { label: `Observation is ${hours} hr old`, stale: true }
}

export function riskColor(risk) {
  if (!risk?.thresholdSource) return 'neutral'
  const classification = risk.classification?.toLowerCase()
  if (classification === 'normal') return 'normal'
  if (classification === 'moderate') return 'moderate'
  if (classification === 'high') return 'high'
  if (classification === 'severe') return 'severe'
  return 'neutral'
}
