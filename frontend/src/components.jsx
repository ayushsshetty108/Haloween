import { NavLink, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { AlertCircle, BadgeCheck, ChevronDown, Clock3, Layers3, LoaderCircle, MapPin, Menu, Radio, RefreshCw, Waves, X } from 'lucide-react'
import { GeoJSON, MapContainer, Marker, Popup, TileLayer } from 'react-leaflet'
import L from 'leaflet'
import { NAV } from './navigation.js'
import { getBoundary } from './services/data.js'
import { liveFreshness, riskColor, USGS_STATION_IDS } from './services/liveStations.js'
import { useLiveStations } from './hooks/LiveStationsContext.jsx'

const icon = (color, active = false) => L.divIcon({ className: '', html: `<span class="station-pin ${active ? 'selected' : ''}" style="--pin:${color}"></span>`, iconSize: [22,22], iconAnchor: [11,11] })
export function Sidebar({ mobileOpen, close }) {
  const location=useLocation()
  useEffect(()=>close(),[location.pathname])
  return <aside className={`sidebar ${mobileOpen?'mobile-open':''}`}>
    <div className="brand"><div className="brand-mark"><Waves size={20}/></div><div><strong>FLOOD<span>CAST</span></strong><small>RIVER INTELLIGENCE</small></div><button className="mobile-close" onClick={close} aria-label="Close navigation"><X size={18}/></button></div>
    <div className="nav-label">WORKSPACE</div><nav>{NAV.map(({to,label,icon:Icon})=><NavLink key={to} to={to} end={to==='/'} className={({isActive})=>`nav-link ${isActive?'active':''}`}><Icon size={17}/><span>{label}</span>{to==='/monitoring'&&<span className="nav-count">04</span>}</NavLink>)}</nav>
    <div className="sidebar-bottom"><div className="system-card"><span className="status-dot"/><div><b>Project data ready</b><small>Local source files detected</small></div><ChevronDown size={14}/></div><div className="profile"><div className="avatar">FC</div><div><b>Floodcast Lab</b><small>Research workspace</small></div><ChevronDown size={14}/></div></div>
  </aside>
}

export function Topbar({ onMenu }) { const location=useLocation();const today=new Intl.DateTimeFormat('en-US',{month:'short',day:'2-digit',year:'numeric'}).format(new Date()).toUpperCase();const label=location.pathname==='/monitoring'?'LIVE + HISTORICAL':'HISTORICAL DATA';return <header className="topbar"><button className="mobile-menu" onClick={onMenu} aria-label="Open navigation"><Menu size={20}/></button><div className="breadcrumb"><span>Workspace</span><b>/</b><strong>{NAV.find(n=>n.to===location.pathname)?.label||'Overview'}</strong></div><div className="top-actions"><span className="live-status"><i/> {label}</span><div className="top-divider"/><div className="date-label">{today}</div></div></header> }

export function PageHeader({ eyebrow, title, subtitle, actions }) { return <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/>{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{actions&&<div className="heading-actions">{actions}</div>}</div> }
export function Panel({ title, subtitle, action, children, className='' }) { return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div>{action}</div>{children}</section> }
export function KPI({ label, value, suffix, icon:Icon, note, tone='blue' }) { return <div className="kpi-card"><div className="kpi-top"><span>{label}</span><span className={`kpi-icon ${tone}`}><Icon size={17}/></span></div><div className="kpi-value">{value}{suffix&&<small>{suffix}</small>}</div><div className="kpi-note">{note}</div></div> }
export function Loading() { return <div className="loading"><span className="spinner"/>Loading verified project data…</div> }
export function EmptyState({ title='Not available yet', children, icon:Icon=Layers3 }) { return <div className="empty-state"><div className="empty-icon"><Icon size={20}/></div><b>{title}</b><p>{children}</p></div> }
export function ErrorState({ error }) { return <div className="inline-error"><Radio size={17}/><span>{error?.message || 'This project dataset could not be loaded.'}</span></div> }
export function Select({ value, onChange, options, label }) { return <label className="select-wrap"><span className="sr-only">{label}</span><select value={value} onChange={e=>onChange(e.target.value)}>{options.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select><ChevronDown size={14}/></label> }
function BoundaryOverlay({ stationId }) {
  const [data,setData]=useState(null);const [error,setError]=useState('');const [loading,setLoading]=useState(true)
  useEffect(()=>{let active=true;setLoading(true);setData(null);setError('');getBoundary(stationId).then(value=>{if(active)setData(value)}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[stationId])
  if (loading) return <div className="map-loading"><LoaderCircle size={15}/>Loading basin boundary…</div>
  if (error) return <div className="map-loading map-error">{error}</div>
  return data?<GeoJSON data={data} style={{color:'#1676c4',weight:2.2,opacity:.95,fillColor:'#57b7ec',fillOpacity:.1,dashArray:'6 5'}}/>:null
}
const RISK_COLORS={normal:'#369b64',moderate:'#dfb735',high:'#e58a32',severe:'#d94f55',neutral:'#71879a'}
const readableValue=value=>value==null||!Number.isFinite(Number(value))?'Unavailable':new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(Number(value))
function StationMarker({ station, selected, onSelect }) {
  const {snapshot}=useLiveStations()
  const live=snapshot?.stations.find(item=>item.stationId===station.id)
  const state=riskColor(live?.risk)
  const markerColor=RISK_COLORS[state]
  const stream=live?.streamflow
  const height=live?.gaugeHeight
  const freshness=liveFreshness(stream)
  return <Marker position={[station.latitude,station.longitude]} icon={icon(markerColor, selected===station.id)} eventHandlers={{click:()=>onSelect?.(station.id)}}>
    <Popup><div className="map-popup live-popup">
      <div className="popup-heading"><span className="popup-station-icon"><MapPin size={15}/></span><div><b>{station.river}</b><span>{station.id} · {station.name}</span></div></div>
      <div className="popup-location">{station.state} · {station.latitude.toFixed(4)}, {station.longitude.toFixed(4)}</div>
      <div className="popup-live-grid">
        <div><small>Observed streamflow</small><b>{readableValue(stream?.value)} <i>{stream?.unit||''}</i></b><span>{stream?.time?new Date(stream.time).toLocaleString():'No live observation returned'}</span><em>USGS observation · {stream?.approvalStatus||'status unavailable'}</em></div>
        <div><small>Observed gauge height</small><b>{readableValue(height?.value)} <i>{height?.unit||''}</i></b><span>{height?.time?new Date(height.time).toLocaleString():'Not reported by this station'}</span></div>
      </div>
      <div className="popup-status"><Clock3 size={13}/><span>{freshness.label}</span><b>{riskColor(live?.risk)==='neutral'?'Risk classification unavailable':`${live.risk.classification} · ${live.risk.thresholdSource}`}</b></div>
      <div className="popup-prediction"><span>FLOODCAST predicted discharge</span><b>{live?.prediction?.predicted_discharge!=null?`${readableValue(live.prediction.predicted_discharge)} ${live.prediction.unit||stream?.unit||''}`:'No validated prediction available'}</b></div>
    </div></Popup>
  </Marker>
}
function LiveMapBadge(){const {snapshot,loading,refreshing,error,refresh}=useLiveStations();const time=snapshot?.fetchedAt?new Date(snapshot.fetchedAt).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}):null;return <div className={`live-map-badge ${error?'warning':''}`}><span className="live-map-dot"/><span>{error?(snapshot?'USGS update delayed':'Live USGS unavailable'):snapshot?.source||'Connecting to USGS'}</span><span className="live-map-updated">{time?`Updated ${time}`:loading?'Loading latest observations':'No successful update'}</span><button onClick={()=>refresh(true)} disabled={refreshing||loading} aria-label="Refresh live station measurements" title={error?.message||'Refresh live data'}><RefreshCw size={13} className={refreshing?'is-spinning':''}/></button></div>}
export function LiveStationSummary({ station }) {
  const {snapshot,loading,error,refreshing,refresh}=useLiveStations()
  const live=snapshot?.stations.find(item=>item.stationId===station.id)
  const stream=live?.streamflow;const height=live?.gaugeHeight;const freshness=liveFreshness(stream)
  return <div className="live-summary">
    <div className="live-summary-head"><div><span className="live-kicker"><i/>{error&&snapshot?'LAST SUCCESSFUL DATA · UPDATE DELAYED':snapshot?.source||'CONNECTING TO USGS'}</span><h3>Latest continuous reading</h3></div><button className="refresh-button" onClick={()=>refresh(true)} disabled={refreshing||loading} aria-label="Refresh live station data"><RefreshCw size={14} className={refreshing?'is-spinning':''}/> Refresh</button></div>
    {loading&&!snapshot?<div className="live-empty"><LoaderCircle size={17}/>Requesting latest measurements from USGS…</div>:<>
      <div className="live-measurement-grid"><div className="live-measurement primary"><span>Observed streamflow <em>USGS · 00060</em></span><b>{readableValue(stream?.value)} <small>{stream?.unit||''}</small></b><span>{stream?.time?new Date(stream.time).toLocaleString():'No continuous flow reading returned'}</span><span className="approval-status">{stream?.approvalStatus||'Approval status unavailable'}</span></div><div className="live-measurement"><span>Observed gauge height <em>USGS · 00065</em></span><b>{readableValue(height?.value)} <small>{height?.unit||''}</small></b><span>{height?.time?new Date(height.time).toLocaleString():'Not reported for this station'}</span><span className="approval-status">{height?.approvalStatus||'Approval status unavailable'}</span></div></div>
      <div className="live-detail-meta"><span className={freshness.stale?'stale':''}><Clock3 size={13}/>{freshness.label}</span><span><BadgeCheck size={13}/>{stream?.approvalStatus||'Data status unavailable'}</span></div>
      <div className="live-prediction-row"><span>FLOODCAST predicted discharge</span><b>{live?.prediction?.predicted_discharge!=null?`${readableValue(live.prediction.predicted_discharge)} ${live.prediction.unit||stream?.unit||''}`:'No validated prediction available'}</b><small>Predictions are kept separate from USGS observations.</small></div>
      {riskColor(live?.risk)==='neutral'?<div className="risk-unavailable"><AlertCircle size={14}/><span>Risk classification unavailable — no verified station-specific flood thresholds are connected.</span></div>:<div className={`risk-supported ${riskColor(live.risk)}`}><span>Threshold-based risk</span><b>{live.risk.classification}</b><small>{live.risk.thresholdSource}</small></div>}
    </>}
    {error&&<div className="live-error"><AlertCircle size={14}/><span>{error.message}</span></div>}
  </div>
}
export function StationMap({ stations, selected, onSelect }) {
  const [mapTone,setMapTone]=useState('dark');const [showBoundary,setShowBoundary]=useState(false)
  const selectedSite=stations.find(site=>site.id===selected)
  return <div className={`map-wrap ${mapTone}-map`}><MapContainer center={[38,-91]} zoom={4} scrollWheelZoom={true} zoomControl={true}>
    <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"/>
    {showBoundary&&selected&&<BoundaryOverlay key={selected} stationId={selected}/>}
    {stations.filter(s=>USGS_STATION_IDS.includes(s.id)&&s.latitude!=null&&s.longitude!=null).map(station=><StationMarker key={station.id} station={station} selected={selected} onSelect={onSelect}/>)}
    </MapContainer>
    <LiveMapBadge/>
    <div className="map-tools"><div className="map-modes" aria-label="Map appearance"><button className={mapTone==='dark'?'selected':''} onClick={()=>setMapTone('dark')} aria-pressed={mapTone==='dark'}>Dark map</button><button className={mapTone==='light'?'selected':''} onClick={()=>setMapTone('light')} aria-pressed={mapTone==='light'}>Light map</button></div><button className={`boundary-toggle ${showBoundary?'selected':''}`} onClick={()=>setShowBoundary(value=>!value)} aria-pressed={showBoundary} disabled={!selected}><Layers3 size={14}/><span>{showBoundary?'Hide basin':'Basin outline'}</span></button></div>
    {showBoundary&&selectedSite&&<div className="boundary-note">Verified NLDI boundary · {selectedSite.id}{selectedSite.id==='07010000'?' · large basin file, loads on request':''}</div>}
    <div className="map-legend risk-legend"><span><i className="legend-dot risk-normal"/>Normal</span><span><i className="legend-dot risk-moderate"/>Moderate</span><span><i className="legend-dot risk-high"/>High</span><span><i className="legend-dot risk-severe"/>Severe</span><span><i className="legend-dot risk-neutral"/>Risk unavailable</span>{showBoundary&&<span><i className="legend-line"/>Verified basin</span>}</div>
  </div>
}
export function formatValue(value, digits=0) { return value==null||!Number.isFinite(value)?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(value) }
export function StatusChip({ children, tone='neutral' }) { return <span className={`status-chip ${tone}`}>{children}</span> }
