import { useEffect, useMemo, useRef, useState } from 'react'
import { maplibreGL } from '@maplibre/maplibre-gl-leaflet'
import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { CircleMarker, MapContainer, Polyline, Popup, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import 'maplibre-gl/dist/maplibre-gl.css'
import { formatDate } from '../../lib/format.js'

const WORLD_CENTER = [20, 0]
const WORLD_ZOOM = 2
const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'

setWorkerUrl(workerUrl)

function point(latitude, longitude) {
  if (latitude === null || latitude === undefined || latitude === '' || longitude === null || longitude === undefined || longitude === '') return null
  const lat = Number(latitude)
  const lon = Number(longitude)
  return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
    ? [lat, lon]
    : null
}

function alertColor(level) {
  if (level === 'red') return '#c94d45'
  if (level === 'orange') return '#df8b2d'
  return '#6d9b78'
}

function shipmentColor(status) {
  if (status === 'delayed' || status === 'at_risk') return '#c94d45'
  if (status === 'in_transit') return '#087f78'
  return '#4e7898'
}

function FitMapToData({ locations }) {
  const map = useMap()
  const didFit = useRef(false)

  useEffect(() => {
    if (didFit.current || locations.length === 0) return
    didFit.current = true
    if (locations.length === 1) map.setView(locations[0], 4)
    else map.fitBounds(locations, { padding: [28, 28], maxZoom: 5 })
  }, [locations, map])

  return null
}

function OpenFreeMapLayer() {
  const map = useMap()

  useEffect(() => {
    const layer = maplibreGL({ style: BASEMAP_STYLE })
    layer.addTo(map)
    return () => layer.remove()
  }, [map])

  return null
}

function ShipmentRoute({ shipment }) {
  const origin = point(shipment.origin_latitude, shipment.origin_longitude)
  const destination = point(shipment.destination_latitude, shipment.destination_longitude)
  const color = shipmentColor(shipment.status)

  return <>
    {origin && destination && <Polyline positions={[origin, destination]} pathOptions={{ color, opacity: 0.68, weight: 2 }} />}
    {origin && <CircleMarker center={origin} radius={5} pathOptions={{ color: '#fff', weight: 2, fillColor: color, fillOpacity: 1 }}>
      <Popup><div className="map-popup"><strong>{shipment.reference}</strong><span>Origin · {shipment.origin}</span><span>{shipment.carrier || 'Carrier not set'} · {shipment.status.replaceAll('_', ' ')}</span></div></Popup>
    </CircleMarker>}
    {destination && <CircleMarker center={destination} radius={5} pathOptions={{ color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.72 }}>
      <Popup><div className="map-popup"><strong>{shipment.reference}</strong><span>Destination · {shipment.destination}</span><span>Promised arrival · {formatDate(shipment.eta)}</span></div></Popup>
    </CircleMarker>}
  </>
}

function DisasterMarker({ event }) {
  const location = point(event.latitude, event.longitude)
  if (!location) return null
  const color = alertColor(event.alert_level)
  return <CircleMarker center={location} radius={9} pathOptions={{ color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.92 }}>
    <Popup><div className="map-popup">
      <strong>{event.title}</strong>
      <span>{event.event_type} · {event.alert_level} alert</span>
      {event.affected_region && <span>{event.affected_region}</span>}
      <span>Updated · {formatDate(event.issued_at, true)}</span>
      {event.source_url && <a href={event.source_url} target="_blank" rel="noreferrer">View GDACS event ↗</a>}
    </div></Popup>
  </CircleMarker>
}

function Metric({ label, value, detail, tone = '' }) {
  return <article className={`map-metric ${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>
}

export default function NetworkMapPage({ data, loading, onNavigate }) {
  const [showShipments, setShowShipments] = useState(true)
  const [showDisasters, setShowDisasters] = useState(true)
  const [includeDelivered, setIncludeDelivered] = useState(false)

  const allShipments = data?.shipments || []
  const disasters = data?.disasters || []
  const counts = data?.counts || {}
  const currentShipments = useMemo(
    () => allShipments.filter((shipment) => includeDelivered || shipment.status !== 'delivered'),
    [allShipments, includeDelivered],
  )
  const locatedShipments = useMemo(
    () => currentShipments.filter((shipment) => point(shipment.origin_latitude, shipment.origin_longitude) || point(shipment.destination_latitude, shipment.destination_longitude)),
    [currentShipments],
  )
  const locatedDisasters = useMemo(
    () => disasters.filter((event) => point(event.latitude, event.longitude)),
    [disasters],
  )
  const locations = useMemo(() => [
    ...(showShipments ? locatedShipments.flatMap((shipment) => [
      point(shipment.origin_latitude, shipment.origin_longitude),
      point(shipment.destination_latitude, shipment.destination_longitude),
    ].filter(Boolean)) : []),
    ...(showDisasters ? locatedDisasters.map((event) => point(event.latitude, event.longitude)).filter(Boolean) : []),
  ], [locatedShipments, locatedDisasters, showShipments, showDisasters])
  const routeCount = currentShipments.filter((shipment) => point(shipment.origin_latitude, shipment.origin_longitude) && point(shipment.destination_latitude, shipment.destination_longitude)).length
  const incompleteRoutes = currentShipments.filter((shipment) => !point(shipment.origin_latitude, shipment.origin_longitude) || !point(shipment.destination_latitude, shipment.destination_longitude))
  const unlocatedShipments = incompleteRoutes.filter((shipment) => !point(shipment.origin_latitude, shipment.origin_longitude) && !point(shipment.destination_latitude, shipment.destination_longitude))
  const feed = data?.feed || {}
  const feedState = feed.status === 'ok' ? 'Last sync successful' : feed.status === 'never' ? 'Waiting for first GDACS sync' : 'Feed needs attention'

  return <div className="network-map-page">
    <div className="map-metrics-grid">
      <Metric label={includeDelivered ? 'Shipments shown' : 'Open shipments'} value={currentShipments.length} detail={`${routeCount} with a full route`} />
      <Metric label="GDACS events" value={disasters.length} detail={`${locatedDisasters.length} with map coordinates`} tone="disaster" />
      <Metric label="Routes needing coordinates" value={incompleteRoutes.length} detail={`${unlocatedShipments.length} have no mapped endpoint`} tone={incompleteRoutes.length ? 'attention' : ''} />
      <Metric label="GDACS updated" value={feed.last_success_at ? formatDate(feed.last_success_at, true) : 'Not yet'} detail={feedState} tone={feed.status === 'ok' ? 'connected' : 'attention'} />
    </div>

    <section className="panel network-map-panel">
      <div className="map-toolbar">
        <div className="map-legend" aria-label="Map legend">
          <span><i className="legend-route" />In transit</span>
          <span><i className="legend-delayed" />Delayed / at risk</span>
          <span><i className="legend-planned" />Planned / delivered</span>
          <span><i className="legend-disaster" />GDACS alerts</span>
        </div>
        <div className="map-toggles">
          <label><input type="checkbox" checked={showShipments} onChange={(event) => setShowShipments(event.target.checked)} /> Shipments</label>
          <label><input type="checkbox" checked={showDisasters} onChange={(event) => setShowDisasters(event.target.checked)} /> Disasters</label>
          <label><input type="checkbox" checked={includeDelivered} onChange={(event) => setIncludeDelivered(event.target.checked)} /> Include delivered</label>
        </div>
      </div>
      <div className="network-map-canvas" aria-label="Interactive world map showing shipments and GDACS disaster events">
        <MapContainer center={WORLD_CENTER} zoom={WORLD_ZOOM} minZoom={1} maxZoom={12} maxBounds={[[-85.0511, -180], [85.0511, 180]]} maxBoundsViscosity={1} scrollWheelZoom={false}>
          <OpenFreeMapLayer />
          <FitMapToData locations={locations} />
          {showShipments && locatedShipments.map((shipment) => <ShipmentRoute key={shipment.id} shipment={shipment} />)}
          {showDisasters && locatedDisasters.map((event) => <DisasterMarker key={event.id} event={event} />)}
        </MapContainer>
        {!locations.length && !loading && <div className="map-empty-overlay"><strong>No mapped coordinates yet</strong><span>GDACS events and shipments appear here when their coordinates are available.</span></div>}
        {loading && <div className="map-loading-overlay"><i />Updating map data…</div>}
      </div>
      <div className="map-footnote"><span>Basemap by OpenFreeMap · © OpenMapTiles · Data © OpenStreetMap contributors</span><span>GDACS is refreshed by the ARES feed worker; the dashboard checks for updates every 30 seconds.</span></div>
    </section>

    <div className="map-detail-grid">
      <section className="panel map-detail-panel">
        <div className="panel-heading"><div><p className="eyebrow">CURRENT HAZARDS</p><h2>GDACS disaster alerts</h2><p>Active source events; map markers are shown when GDACS provides coordinates.</p></div><span className={`map-feed-badge ${feed.status === 'ok' ? 'is-connected' : ''}`}><i />{feedState}</span></div>
        {disasters.length
          ? <div className="map-event-list">{disasters.slice(0, 8).map((event) => <article className="map-event-row" key={event.id}>
              <i style={{ '--event-color': alertColor(event.alert_level) }} />
              <div><strong>{event.title}</strong><span>{[event.event_type, event.affected_region].filter(Boolean).join(' · ') || 'Natural disaster'}</span></div>
              <small>{event.alert_level}</small>
            </article>)}</div>
          : <p className="map-empty-list">{loading ? 'Loading GDACS events…' : 'No active GDACS events are available. Check that the GDACS worker is running.'}</p>}
        {counts.disasters_truncated && <p className="map-limit-note">Showing the latest {counts.disasters_returned} of {counts.disasters_total} active events.</p>}
        {feed.last_error && <p className="map-feed-error">Latest feed error: {feed.last_error}</p>}
      </section>

      <section className="panel map-detail-panel">
        <div className="panel-heading"><div><p className="eyebrow">LOCATION DATA</p><h2>Routes needing coordinates</h2><p>ARES does not guess locations from free-text city names.</p></div><button type="button" className="text-button" onClick={() => onNavigate?.('imports')}>Open data onboarding →</button></div>
        {incompleteRoutes.length
          ? <>
              <div className="map-unlocated-note">Add paired latitude and longitude values for both endpoints in the shipment CSV to plot full routes.</div>
              <div className="map-event-list">{incompleteRoutes.slice(0, 5).map((shipment) => <article className="map-event-row" key={shipment.id}>
                <i className="legend-route" />
                <div><strong>{shipment.reference}</strong><span>{shipment.origin} → {shipment.destination}</span></div>
                <small>{!point(shipment.origin_latitude, shipment.origin_longitude) && !point(shipment.destination_latitude, shipment.destination_longitude) ? 'needs both' : !point(shipment.origin_latitude, shipment.origin_longitude) ? 'needs origin' : 'needs destination'}</small>
              </article>)}</div>
              {incompleteRoutes.length > 5 && <p className="map-limit-note">And {incompleteRoutes.length - 5} more shipments need coordinates.</p>}
            </>
          : <p className="map-empty-list">All displayed shipments have coordinates for both route endpoints.</p>}
        {counts.shipments_truncated && <p className="map-limit-note">The map is showing the first {counts.shipments_returned} of {counts.shipments_total} shipment records.</p>}
      </section>
    </div>
  </div>
}
