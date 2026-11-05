import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUpRight, MapPin, Waves } from 'lucide-react'
import { getStations } from '../services/data.js'
import { useData } from '../hooks/useData.js'
import { EmptyState, ErrorState, Loading, PageHeader, Panel, Select, StationMap, StatusChip, formatValue } from '../components.jsx'

export default function Monitoring() {
  const {data,error,loading}=useData(getStations,'stations'); const [selected,setSelected]=useState('01646500'); const navigate=useNavigate()
  const station=data?.find(s=>s.id===selected)
  if(loading)return <Loading/>; if(error)return <ErrorState error={error}/>
  return <><PageHeader eyebrow="GAUGE NETWORK" title="Station monitoring" subtitle="Explore gauge locations and review the latest verified observations." actions={<StatusChip tone="green">{data.length} VERIFIED LOCATIONS</StatusChip>}/>
    <div className="monitor-grid"><Panel title="United States gauge map" subtitle="Select a marker to focus station details" className="map-panel monitor-map"><StationMap stations={data} selected={selected} onSelect={setSelected}/></Panel>
    <Panel title="Selected station" subtitle="USGS monitoring location" action={<Select value={selected} onChange={setSelected} options={data.map(s=>({value:s.id,label:s.id}))} label="Select station"/>}>
      {station&&<><div className="detail-title"><span className="river-icon"><Waves size={20}/></span><div><b>{station.river}</b><small>{station.name}</small></div><StatusChip tone="blue">USGS SITE</StatusChip></div><div className="detail-kpis"><div><span>Station ID</span><b>{station.id}</b></div><div><span>Location</span><b>{station.state}</b></div><div><span>Latitude</span><b>{station.latitude?.toFixed(4)??'—'}°</b></div><div><span>Longitude</span><b>{station.longitude?.toFixed(4)??'—'}°</b></div></div><div className="detail-reading"><div><span>Latest daily mean</span><b>{station.latest?formatValue(station.latest.discharge):'—'} <small>{station.latest?'cfs':''}</small></b><small>{station.latest?.date||'No observation available'}</small></div><Waves size={29}/></div><div className="detail-kpis"><div><span>Drainage area</span><b>{formatValue(station.drainageArea)} sq mi</b></div><div><span>Historical records</span><b>{formatValue(station.records)}</b></div></div><button className="button-primary full-button" onClick={()=>navigate('/predictions')}>View discharge history <ArrowUpRight size={15}/></button></>}
    </Panel></div>
    <Panel title="Monitoring locations" subtitle="Coordinates and latest observed discharge"><div className="table-scroll"><table><thead><tr><th>Station</th><th>USGS ID</th><th>Coordinates</th><th>Drainage area</th><th>Latest daily mean</th><th>Observation date</th></tr></thead><tbody>{data.map(s=><tr key={s.id} onClick={()=>setSelected(s.id)} className="click-row"><td><b>{s.river}</b><small>{s.name}</small></td><td className="mono">{s.id}</td><td className="mono">{s.latitude?.toFixed(4)}, {s.longitude?.toFixed(4)}</td><td>{formatValue(s.drainageArea)} sq mi</td><td>{s.latest?`${formatValue(s.latest.discharge)} cfs`:'—'}</td><td>{s.latest?.date||'—'}</td></tr>)}</tbody></table></div></Panel>
  </>
}
