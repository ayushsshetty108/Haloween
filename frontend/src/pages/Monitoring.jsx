import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUpRight, Waves } from 'lucide-react'
import { getStations } from '../services/data.js'
import { useData } from '../hooks/useData.js'
import { ErrorState, LiveStationSummary, Loading, PageHeader, Panel, Select, StationMap, StatusChip, formatValue } from '../components.jsx'

export default function Monitoring() {
  const {data,error,loading}=useData(getStations,'stations'); const [selected,setSelected]=useState('01646500'); const navigate=useNavigate()
  const station=data?.find(s=>s.id===selected)
  if(loading)return <Loading/>; if(error)return <ErrorState error={error}/>
  return <><PageHeader eyebrow="GAUGE NETWORK" title="Station monitoring" subtitle="Explore gauge locations and review the latest continuous USGS observations." actions={<StatusChip tone="blue">{data.length} USGS LOCATIONS</StatusChip>}/>
    <div className="monitor-grid"><Panel title="United States gauge map" subtitle="Open a station marker for observed flow, gauge height, freshness, and data status" className="map-panel monitor-map"><StationMap stations={data} selected={selected} onSelect={setSelected}/></Panel>
    <Panel title="Selected station" subtitle="USGS monitoring location" action={<Select value={selected} onChange={setSelected} options={data.map(s=>({value:s.id,label:s.id}))} label="Select station"/>}>
      {station&&<><div className="detail-title"><span className="river-icon"><Waves size={20}/></span><div><b>{station.river}</b><small>{station.name}</small></div><StatusChip tone="blue">USGS SITE</StatusChip></div><div className="detail-kpis"><div><span>Station ID</span><b>{station.id}</b></div><div><span>Location</span><b>{station.state}</b></div><div><span>Latitude</span><b>{station.latitude?.toFixed(4)??'—'}°</b></div><div><span>Longitude</span><b>{station.longitude?.toFixed(4)??'—'}°</b></div></div><LiveStationSummary station={station}/><div className="detail-kpis"><div><span>Drainage area</span><b>{formatValue(station.drainageArea)} sq mi</b></div><div><span>Historical records</span><b>{formatValue(station.records)}</b></div></div><button className="button-primary full-button" onClick={()=>navigate('/predictions')}>View discharge history <ArrowUpRight size={15}/></button></>}
    </Panel></div>
    <Panel title="Monitoring locations" subtitle="Historical daily means from the local project records (not live readings)"><div className="table-scroll"><table><thead><tr><th>Station</th><th>USGS ID</th><th>Coordinates</th><th>Drainage area</th><th>Latest historical daily mean</th><th>Record date</th></tr></thead><tbody>{data.map(s=><tr key={s.id} onClick={()=>setSelected(s.id)} className="click-row"><td><b>{s.river}</b><small>{s.name}</small></td><td className="mono">{s.id}</td><td className="mono">{s.latitude?.toFixed(4)}, {s.longitude?.toFixed(4)}</td><td>{formatValue(s.drainageArea)} sq mi</td><td>{s.latest?`${formatValue(s.latest.discharge)} cfs`:'—'}</td><td>{s.latest?.date||'—'}</td></tr>)}</tbody></table></div></Panel>
  </>
}
