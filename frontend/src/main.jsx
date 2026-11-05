import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'leaflet/dist/leaflet.css'
import './styles.css'
import App from './App.jsx'
import { LiveStationsProvider } from './hooks/LiveStationsContext.jsx'

createRoot(document.getElementById('root')).render(<React.StrictMode><LiveStationsProvider><BrowserRouter><App /></BrowserRouter></LiveStationsProvider></React.StrictMode>)
