import { NavLink, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Bell, ChevronDown, Layers3, LoaderCircle, Map as MapIcon, Menu, Mountain, Radio, Satellite, Waves, X } from 'lucide-react'
import { GeoJSON, MapContainer, Marker, Popup, TileLayer } from 'react-leaflet'
import L from 'leaflet'
import { NAV } from './navigation.js'
import { getBoundary } from './services/data.js'

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

export function Topbar({ onMenu }) { const today=new Intl.DateTimeFormat('en-US',{month:'short',day:'2-digit',year:'numeric'}).format(new Date()).toUpperCase();return <header className="topbar"><button className="mobile-menu" onClick={onMenu} aria-label="Open navigation"><Menu size={20}/></button><div className="breadcrumb"><span>Workspace</span><b>/</b><strong>{NAV.find(n=>n.to===useLocation().pathname)?.label||'Overview'}</strong></div><div className="top-actions"><span className="live-status"><i/> HISTORICAL DATA</span><div className="top-divider"/><div className="date-label">{today}</div></div></header> }

export function PageHeader({ eyebrow, title, subtitle, actions }) { return <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/>{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{actions&&<div className="heading-actions">{actions}</div>}</div> }
export function Panel({ title, subtitle, action, children, className='' }) { return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div>{action}</div>{children}</section> }
export function KPI({ label, value, suffix, icon:Icon, note, tone='green' }) { return <div className="kpi-card"><div className="kpi-top"><span>{label}</span><span className={`kpi-icon ${tone}`}><Icon size={17}/></span></div><div className="kpi-value">{value}{suffix&&<small>{suffix}</small>}</div><div className="kpi-note">{note}</div></div> }
export function Loading() { return <div className="loading"><span className="spinner"/>Loading verified project data…</div> }
export function EmptyState({ title='Not available yet', children, icon:Icon=Layers3 }) { return <div className="empty-state"><div className="empty-icon"><Icon size={20}/></div><b>{title}</b><p>{children}</p></div> }
export function ErrorState({ error }) { return <div className="inline-error"><Radio size={17}/><span>{error?.message || 'This project dataset could not be loaded.'}</span></div> }
export function Select({ value, onChange, options, label }) { return <label className="select-wrap"><span className="sr-only">{label}</span><select value={value} onChange={e=>onChange(e.target.value)}>{options.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select><ChevronDown size={14}/></label> }
function BoundaryOverlay({ stationId }) {
  const [data,setData]=useState(null);const [error,setError]=useState('');const [loading,setLoading]=useState(true)
  useEffect(()=>{let active=true;setLoading(true);setData(null);setError('');getBoundary(stationId).then(value=>{if(active)setData(value)}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[stationId])
  if (loading) return <div className="map-loading"><LoaderCircle size={15}/>Loading basin boundary…</div>
  if (error) return <div className="map-loading map-error">{error}</div>
  return data?<GeoJSON data={data} style={{color:'#62e5b1',weight:2.2,opacity:.95,fillColor:'#24bc83',fillOpacity:.08,dashArray:'6 5'}}/>:null
}
const TILESETS={
  dark:{url:'https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png',attribution:'&copy; <a href="https://carto.com/attributions">CARTO</a> &copy; OpenStreetMap'},
  terrain:{url:'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',attribution:'&copy; <a href="https://carto.com/attributions">CARTO</a> &copy; OpenStreetMap'},
  satellite:{url:'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',attribution:'Tiles &copy; Esri'},
}
export function StationMap({ stations, selected, onSelect }) {
  const [basemap,setBasemap]=useState('dark');const [showBoundary,setShowBoundary]=useState(false)
  const selectedSite=stations.find(site=>site.id===selected);const tile=TILESETS[basemap]
  return <div className="map-wrap"><MapContainer center={[38,-91]} zoom={4} scrollWheelZoom={true} zoomControl={true}>
    <TileLayer key={basemap} attribution={tile.attribution} url={tile.url}/>
    {showBoundary&&selected&&<BoundaryOverlay key={selected} stationId={selected}/>}
    {stations.filter(s=>s.latitude!=null&&s.longitude!=null).map((s,i)=><Marker key={s.id} position={[s.latitude,s.longitude]} icon={icon(i%2?'#38bdf8':'#22c58b', selected===s.id)} eventHandlers={{click:()=>onSelect?.(s.id)}}><Popup><div className="map-popup"><b>{s.river}</b><span>{s.id} · {s.name}</span><span>{s.latitude.toFixed(4)}°, {s.longitude.toFixed(4)}°</span><span>{s.latest ? `${s.latest.discharge.toLocaleString()} cfs · ${s.latest.date}` : 'No discharge record'}</span></div></Popup></Marker>)}
    </MapContainer>
    <div className="map-tools"><div className="map-modes" aria-label="Basemap style">{[['dark',MapIcon,'Dark'],['terrain',Mountain,'Terrain'],['satellite',Satellite,'Satellite']].map(([key,Icon,label])=><button key={key} className={basemap===key?'selected':''} onClick={()=>setBasemap(key)} aria-pressed={basemap===key}><Icon size={14}/><span>{label}</span></button>)}</div><button className={`boundary-toggle ${showBoundary?'selected':''}`} onClick={()=>setShowBoundary(value=>!value)} aria-pressed={showBoundary} disabled={!selected}><Layers3 size={14}/><span>{showBoundary?'Hide basin':'Basin outline'}</span></button></div>
    {showBoundary&&selectedSite&&<div className="boundary-note">Verified NLDI boundary · {selectedSite.id}{selectedSite.id==='07010000'?' · large basin file, loads on request':''}</div>}
    <div className="map-legend"><span><i className="legend-dot mint"/>Gauge location</span><span><i className="legend-dot selected-marker"/>Focused station</span>{showBoundary&&<span><i className="legend-line"/>Verified basin</span>}</div>
  </div>
}
export function formatValue(value, digits=0) { return value==null||!Number.isFinite(value)?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(value) }
export function StatusChip({ children, tone='neutral' }) { return <span className={`status-chip ${tone}`}>{children}</span> }
