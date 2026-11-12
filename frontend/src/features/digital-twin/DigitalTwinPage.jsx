import { useEffect, useMemo, useRef, useState } from 'react'
import { maplibreGL } from '@maplibre/maplibre-gl-leaflet'
import { setWorkerUrl } from 'maplibre-gl'
import L from 'leaflet'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { GeoJSON, MapContainer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import 'maplibre-gl/dist/maplibre-gl.css'
import { request } from '../../lib/api.js'
import { formatDate, formatRelativeTime } from '../../lib/format.js'

const MAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
const GRAPH_WIDTH = 1220
const TYPE_COLUMNS = {
  supplier: { x: 90, title: 'SUPPLIERS', icon: 'S' },
  purchase_order: { x: 300, title: 'PURCHASE ORDERS', icon: 'PO' },
  material: { x: 510, title: 'MATERIALS', icon: 'M' },
  warehouse: { x: 720, title: 'WAREHOUSES', icon: 'W' },
  shipment: { x: 930, title: 'SHIPMENTS', icon: 'SH' },
  disruption: { x: 1130, title: 'DISRUPTIONS', icon: '!' },
}
const SCENARIOS = [
  ['supplier_failure', 'Supplier failure', 'supplier'],
  ['warehouse_failure', 'Warehouse failure', 'warehouse'],
  ['shipment_delay', 'Shipment delay', 'shipment'],
  ['route_disruption', 'Route disruption', 'shipment'],
  ['material_shortage', 'Material shortage', 'material'],
  ['demand_surge', 'Demand surge', 'material'],
]

setWorkerUrl(workerUrl)

function nodeColor(node) {
  if (node.risk_level === 'critical') return '#c6564e'
  if (node.risk_level === 'warning') return '#c78e37'
  if (node.risk_level === 'unknown') return '#89979a'
  return '#0b847c'
}

function graphLayout(nodes) {
  const priorities = { critical: 0, warning: 1, normal: 2, unknown: 3 }
  const groups = Object.keys(TYPE_COLUMNS).reduce((result, type) => {
    result[type] = nodes.filter((node) => node.type === type)
      .sort((a, b) => priorities[a.risk_level] - priorities[b.risk_level] || a.name.localeCompare(b.name))
    return result
  }, {})
  const positions = {}
  Object.entries(groups).forEach(([type, group]) => {
    group.forEach((node, index) => {
      positions[node.id] = { x: TYPE_COLUMNS[type].x, y: 72 + index * 54 }
    })
  })
  return { groups, positions, height: Math.max(500, ...Object.values(groups).map((group) => 110 + group.length * 54)) }
}

function Shape({ type, fill }) {
  const stroke = '#fff'
  if (type === 'supplier') return <circle r="13" fill={fill} stroke={stroke} strokeWidth="2" />
  if (type === 'warehouse') return <rect x="-12" y="-12" width="24" height="24" rx="3" fill={fill} stroke={stroke} strokeWidth="2" />
  if (type === 'material') return <polygon points="0,-15 14,0 0,15 -14,0" fill={fill} stroke={stroke} strokeWidth="2" />
  if (type === 'purchase_order') return <rect x="-17" y="-11" width="34" height="22" rx="8" fill={fill} stroke={stroke} strokeWidth="2" />
  if (type === 'shipment') return <polygon points="-14,-9 0,-16 14,-9 14,9 0,16 -14,9" fill={fill} stroke={stroke} strokeWidth="2" />
  return <polygon points="0,-16 15,12 -15,12" fill={fill} stroke={stroke} strokeWidth="2" />
}

function Basemap() {
  const map = useMap()
  useEffect(() => {
    const layer = maplibreGL({ style: MAP_STYLE })
    layer.addTo(map)
    return () => layer.remove()
  }, [map])
  return null
}

function FitGeoData({ features }) {
  const map = useMap()
  const didFit = useRef(false)
  useEffect(() => {
    if (didFit.current || !features?.length) return
    const points = []
    const walk = (coordinates) => {
      if (!Array.isArray(coordinates)) return
      if (coordinates.length >= 2 && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
        points.push([coordinates[1], coordinates[0]])
      } else coordinates.forEach(walk)
    }
    features.forEach((feature) => walk(feature.geometry?.coordinates))
    if (points.length === 1) map.setView(points[0], 4)
    else if (points.length > 1) map.fitBounds(points, { padding: [24, 24], maxZoom: 5 })
    didFit.current = true
  }, [features, map])
  return null
}

function featureStyle(feature) {
  const type = feature?.properties?.type
  const color = type === 'disruption'
    ? feature?.properties?.status === 'resolved' ? '#7d898a' : '#c6564e'
    : type === 'shipment' ? '#4c8198'
      : type === 'shipment_endpoint' ? '#0b847c'
        : '#667f88'
  return { color, weight: type === 'disruption' ? 2 : 2, opacity: 0.82, fillColor: color, fillOpacity: type === 'disruption' ? 0.16 : 0.35 }
}

function bindFeaturePopup(feature, layer, onAnalyze) {
  const content = document.createElement('div')
  const title = document.createElement('strong')
  title.textContent = feature?.properties?.name || 'Supply-chain location'
  content.appendChild(title)
  for (const label of [feature?.properties?.type, feature?.properties?.status, feature?.properties?.location_source, feature?.properties?.route_display].filter(Boolean)) {
    const row = document.createElement('div')
    row.textContent = String(label).replaceAll('_', ' ')
    content.appendChild(row)
  }
  if (feature?.properties?.type === 'disruption' && feature?.id && onAnalyze) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'twin-map-impact-button'
    button.textContent = 'Analyze affected entities'
    button.addEventListener('click', () => onAnalyze(String(feature.id).split(':').at(-1)))
    content.appendChild(button)
  }
  layer.bindPopup(content)
}

function TwinMap({ geo, onAnalyze }) {
  const features = geo?.features || []
  return <div className="twin-map-canvas">
    <MapContainer center={[20, 0]} zoom={2} minZoom={1} maxZoom={12} scrollWheelZoom={false}>
      <Basemap />
      <FitGeoData features={features} />
      {features.map((feature) => <GeoJSON key={feature.id} data={feature} style={featureStyle} onEachFeature={(item, layer) => bindFeaturePopup(item, layer, onAnalyze)}
        pointToLayer={(item, latlng) => L.circleMarker(latlng, { radius: item.properties?.type === 'disruption' ? 8 : 5, ...featureStyle(item) })} />)}
    </MapContainer>
    {!features.length && <div className="twin-map-empty"><strong>{geo?.counts?.features ? 'No mapped features match these filters' : 'No mapped locations yet'}</strong><span>{geo?.counts?.features ? 'Adjust the map search or entity filter.' : 'Add real facility and shipment coordinates or sync GDACS geometry to see the network here.'}</span></div>}
  </div>
}

function Metric({ title, value, detail, tone = '' }) {
  return <article className={`twin-kpi ${tone}`}><span>{title}</span><strong>{value ?? '—'}</strong><small>{detail}</small></article>
}

function EntityPanel({ node, detail, busy, onAnalyze }) {
  if (!node) return <div className="twin-detail-empty"><strong>Select a network entity</strong><span>Choose a node to inspect its recorded fields and direct relationships.</span></div>
  const entity = detail?.entity || node
  const metadata = entity.metadata || {}
  return <div className="twin-entity-panel">
    <div className="twin-entity-heading"><span className={`twin-type-mark ${entity.type}`}><svg viewBox="-20 -20 40 40"><Shape type={entity.type} fill={nodeColor(entity)} /></svg></span><div><small>{entity.type.replaceAll('_', ' ')}</small><strong>{entity.name}</strong></div></div>
    <div className="twin-entity-facts"><span>Status <b>{entity.status?.replaceAll('_', ' ') || 'unknown'}</b></span><span>Risk <b>{entity.risk_level || 'unknown'}</b></span><span>Location <b>{entity.geographic_data_available ? 'coordinates available' : 'geographic data unavailable'}</b></span></div>
    {Object.entries(entity.kpis || {}).map(([key, value]) => <div className="twin-detail-row" key={key}><span>{key.replaceAll('_', ' ')}</span><b>{String(value)}</b></div>)}
    {Object.entries(metadata).filter(([key, value]) => !['source_geometry', 'route_coordinates'].includes(key) && value !== null && value !== '').slice(0, 12).map(([key, value]) => <div className="twin-detail-row" key={key}><span>{key.replaceAll('_', ' ')}</span><b>{Array.isArray(value) ? value.join(', ') : String(value)}</b></div>)}
    {entity.type === 'disruption' && <button className="primary-button twin-action" disabled={busy} onClick={() => onAnalyze(entity.entity_id)}>{busy ? 'Analyzing…' : 'Analyze impact'}</button>}
    {detail?.relationships?.length > 0 && <div className="twin-relationship-list"><strong>Direct relationships</strong>{detail.relationships.slice(0, 8).map((edge) => <span key={edge.id}>{edge.type.replaceAll('_', ' ')} · {edge.source === node.id ? edge.target.split(':')[0] : edge.source.split(':')[0]}</span>)}</div>}
  </div>
}

export default function DigitalTwinPage({ data, loading, liveUpdates }) {
  const [graph, setGraph] = useState({ nodes: [], edges: [], pagination: { page: 1, page_count: 1, count: 0 }, graph_counts: {} })
  const [pageLoading, setPageLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [riskFilter, setRiskFilter] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const [selectedDetail, setSelectedDetail] = useState(null)
  const [detailError, setDetailError] = useState('')
  const [impact, setImpact] = useState(null)
  const [impactBusy, setImpactBusy] = useState(false)
  const [scenarioType, setScenarioType] = useState(SCENARIOS[0][0])
  const [scenarioEntity, setScenarioEntity] = useState('')
  const [horizonDays, setHorizonDays] = useState(30)
  const [scenarioValue, setScenarioValue] = useState('7')
  const [simulation, setSimulation] = useState(null)
  const [simulationBusy, setSimulationBusy] = useState(false)
  const [geoTypeFilter, setGeoTypeFilter] = useState('all')
  const [geoSearch, setGeoSearch] = useState('')
  const [pageError, setPageError] = useState('')
  const [positions, setPositions] = useState({})
  const [dragging, setDragging] = useState('')
  const [viewBox, setViewBox] = useState({ x: 0, y: 0, width: GRAPH_WIDTH, height: 650 })
  const svgRef = useRef(null)
  const panRef = useRef(null)

  useEffect(() => {
    if (!data?.graph) return
    setGraph(data.graph)
    setPositions({})
  }, [data?.graph?.generated_at])

  const visibleNodes = useMemo(() => graph.nodes.filter((node) =>
    (typeFilter === 'all' || node.type === typeFilter)
    && (riskFilter === 'all' || node.risk_level === riskFilter)
    && (!search || `${node.name} ${node.id}`.toLowerCase().includes(search.toLowerCase().trim())),
  ), [graph.nodes, typeFilter, riskFilter, search])
  const layout = useMemo(() => graphLayout(visibleNodes), [visibleNodes])
  const nodePositions = { ...layout.positions, ...positions }
  const selected = graph.nodes.find((node) => node.id === selectedId) || null
  const totalNodes = graph.pagination?.count ?? graph.nodes.length
  const pageCount = graph.pagination?.page_count || 1
  const currentPage = graph.pagination?.page || 1
  const scenarioMeta = SCENARIOS.find(([key]) => key === scenarioType) || SCENARIOS[0]
  const scenarioEntities = graph.nodes.filter((node) => node.type === scenarioMeta[2])
  const visibleGeoFeatures = useMemo(() => (data?.geo?.features || []).filter((feature) => {
    const type = feature.properties?.type
    const typeMatches = geoTypeFilter === 'all' || type === geoTypeFilter
      || (geoTypeFilter === 'shipment' && type === 'shipment_endpoint')
    const searchMatches = !geoSearch || `${feature.properties?.name || ''} ${feature.properties?.shipment || ''}`.toLowerCase().includes(geoSearch.toLowerCase().trim())
    return typeMatches && searchMatches
  }), [data?.geo?.features, geoTypeFilter, geoSearch])

  useEffect(() => {
    if (!selected) {
      setSelectedDetail(null)
      return undefined
    }
    const controller = new AbortController()
    setDetailError('')
    const entityPath = `/digital-twin/entities/${selected.type}/${selected.entity_id}/`
    request(entityPath, { signal: controller.signal }).then(setSelectedDetail).catch((error) => {
      if (error.name !== 'AbortError') setDetailError(error.message)
    })
    return () => controller.abort()
  }, [selected?.id])

  useEffect(() => {
    if (!scenarioEntities.length) { setScenarioEntity(''); return }
    if (!scenarioEntities.some((node) => node.entity_id === scenarioEntity)) setScenarioEntity(scenarioEntities[0].entity_id)
  }, [scenarioType, graph.nodes, scenarioEntities.length])

  async function loadNextPage() {
    if (currentPage >= pageCount || pageLoading) return
    setPageLoading(true)
    setPageError('')
    try {
      const next = await request(`/digital-twin/graph/?page=${currentPage + 1}&page_size=100`)
      setGraph((current) => ({ ...next, nodes: [...current.nodes, ...next.nodes],
        edges: [...new Map([...current.edges, ...next.edges].map((edge) => [edge.id, edge])).values()] }))
    } catch (error) {
      setPageError(error.message)
    } finally {
      setPageLoading(false)
    }
  }

  async function analyzeImpact(disruptionId) {
    setImpactBusy(true)
    setImpact(null)
    setPageError('')
    try { setImpact(await request(`/digital-twin/impacts/${disruptionId}/`)) }
    catch (error) { setPageError(error.message) }
    finally { setImpactBusy(false) }
  }

  async function runSimulation(event) {
    event.preventDefault()
    if (!scenarioEntity) return
    setSimulationBusy(true)
    setPageError('')
    const body = { scenario_type: scenarioType, entity_id: scenarioEntity, horizon_days: Number(horizonDays) }
    if (scenarioType === 'shipment_delay' || scenarioType === 'route_disruption') body.delay_days = Number(scenarioValue)
    if (scenarioType === 'material_shortage') body.shortage_quantity = scenarioValue
    if (scenarioType === 'demand_surge') body.demand_increase_percent = scenarioValue
    try {
      const saved = await request('/digital-twin/simulations/', { method: 'POST', body: JSON.stringify(body) })
      setSimulation(saved)
    } catch (error) { setPageError(error.message) }
    finally { setSimulationBusy(false) }
  }

  function graphPointerDown(event, nodeId) {
    event.stopPropagation()
    setSelectedId(nodeId)
    setDragging(nodeId)
    event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId)
  }

  function graphPointerMove(event) {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    if (dragging) {
      const x = Math.max(24, Math.min(GRAPH_WIDTH - 24, (event.clientX - rect.left) / rect.width * viewBox.width + viewBox.x))
      const y = Math.max(54, Math.min(viewBox.height - 24, (event.clientY - rect.top) / rect.height * viewBox.height + viewBox.y))
      setPositions((current) => ({ ...current, [dragging]: { x, y } }))
    } else if (panRef.current) {
      const scaleX = viewBox.width / rect.width
      const scaleY = viewBox.height / rect.height
      setViewBox((current) => ({ ...current, x: panRef.current.x - (event.clientX - panRef.current.clientX) * scaleX,
        y: panRef.current.y - (event.clientY - panRef.current.clientY) * scaleY }))
    }
  }

  function zoomGraph(direction) {
    setViewBox((current) => {
      const factor = direction > 0 ? 0.82 : 1.22
      const width = Math.max(500, Math.min(GRAPH_WIDTH * 2, current.width * factor))
      const height = Math.max(300, Math.min(layout.height * 1.5, current.height * factor))
      return { x: current.x + (current.width - width) / 2, y: current.y + (current.height - height) / 2, width, height }
    })
  }

  const neighborSets = useMemo(() => {
    const upstream = new Set([selectedId])
    const downstream = new Set([selectedId])
    let changed = true
    while (changed) {
      changed = false
      graph.edges.forEach((edge) => {
        if (downstream.has(edge.source) && !downstream.has(edge.target)) { downstream.add(edge.target); changed = true }
        if (upstream.has(edge.target) && !upstream.has(edge.source)) { upstream.add(edge.source); changed = true }
      })
    }
    return { upstream, downstream }
  }, [graph.edges, selectedId])

  const generatedAt = data?.graph?.generated_at
  const syncLabel = data?.sync?.last_change_at ? formatRelativeTime(data.sync.last_change_at, Date.now()) : 'Waiting for first change'
  const gdacsFeed = data?.sync?.sources?.find((source) => source.key === 'gdacs-recent-disasters')
  const gdacsSyncLabel = gdacsFeed?.last_success_at ? formatRelativeTime(gdacsFeed.last_success_at, Date.now()) : 'never synced'
  const inventoryValue = data?.health?.inventory_value
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(data.health.inventory_value))
    : '0'

  return <div className="digital-twin-page">
    <div className="twin-health-grid">
      <Metric title="Active suppliers" value={`${data?.health?.suppliers_active ?? '—'} / ${data?.health?.suppliers_total ?? '—'}`} detail={`${data?.health?.suppliers_high_risk ?? '—'} high-risk records`} />
      <Metric title="Warehouses" value={data?.health?.warehouses_total} detail={`${data?.health?.warehouses_active ?? '—'} active`} />
      <Metric title="Materials" value={data?.health?.materials_total} detail={`${data?.health?.potential_shortages ?? '—'} with low stock`} />
      <Metric title="Inventory value" value={inventoryValue} detail="Currency not normalized" />
      <Metric title="Active shipments" value={data?.health?.active_shipments} detail={`${data?.health?.delayed_shipments ?? '—'} delayed`} />
      <Metric title="Open purchase orders" value={data?.health?.open_purchase_orders} detail="Non-received, non-cancelled" />
      <Metric title="Disrupted facilities" value={data?.health?.disrupted_facilities} detail="Blocked suppliers and inactive warehouses" tone={data?.health?.disrupted_facilities ? 'attention' : ''} />
      <Metric title="Locations missing coordinates" value={(data?.health?.geographic_data_unavailable?.suppliers || 0) + (data?.health?.geographic_data_unavailable?.warehouses || 0)} detail="Supplier and warehouse records" tone="muted" />
    </div>

    <section className="panel twin-panel">
      <div className="twin-panel-heading"><div><p className="eyebrow">NETWORK STRUCTURE</p><h2>Operational dependency graph</h2><p>Nodes and links are generated from stored ARES supplier, PO, material, warehouse, shipment, and disruption records.</p></div>
        <div className="twin-sync-chip"><i className={liveUpdates === 'connected' ? 'is-live' : ''} /><span>{liveUpdates === 'connected' ? 'WebSocket live' : 'Polling recovery'}</span><small>Last change {syncLabel} · GDACS {gdacsFeed?.status || 'not synced'} · {gdacsSyncLabel}</small></div></div>
      <div className="twin-graph-controls">
        <input aria-label="Search graph" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search supplier, PO, material…" />
        <select aria-label="Filter node type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">All entity types</option>{Object.entries(TYPE_COLUMNS).map(([key, value]) => <option key={key} value={key}>{value.title.replaceAll('_', ' ')}</option>)}</select>
        <select aria-label="Filter risk" value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}><option value="all">All risk levels</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="normal">Normal</option><option value="unknown">Unknown</option></select>
        <div className="twin-zoom-controls"><button type="button" aria-label="Zoom in" onClick={() => zoomGraph(1)}>＋</button><button type="button" aria-label="Zoom out" onClick={() => zoomGraph(-1)}>−</button></div>
      </div>
      <div className="twin-graph-legend"><span><i className="normal" />Normal</span><span><i className="warning" />Warning</span><span><i className="critical" />Critical</span><span><i className="unknown" />Unknown</span><small>Drag nodes · drag canvas to pan · scroll to zoom</small></div>
      <div className="twin-graph-viewport">
        {visibleNodes.length ? <svg ref={svgRef} className="twin-graph-svg" viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`} style={{ height: `${layout.height}px` }} role="img" aria-label="Interactive supply chain dependency graph" onPointerMove={graphPointerMove} onPointerUp={() => { setDragging(''); panRef.current = null }} onPointerLeave={() => { setDragging(''); panRef.current = null }} onPointerDown={(event) => { if (event.target === svgRef.current) panRef.current = { x: viewBox.x, y: viewBox.y, clientX: event.clientX, clientY: event.clientY } }} onWheel={(event) => { event.preventDefault(); zoomGraph(event.deltaY < 0 ? 1 : -1) }}>
          {Object.entries(TYPE_COLUMNS).map(([type, value]) => <text key={type} className="twin-column-title" x={value.x} y="27" textAnchor="middle">{value.title}</text>)}
          {graph.edges.map((edge) => {
            const start = nodePositions[edge.source]
            const end = nodePositions[edge.target]
            if (!start || !end || !visibleNodes.some((node) => node.id === edge.source) || !visibleNodes.some((node) => node.id === edge.target)) return null
            const pathActive = selectedId && ((neighborSets.downstream.has(edge.source) && neighborSets.downstream.has(edge.target))
              || (neighborSets.upstream.has(edge.source) && neighborSets.upstream.has(edge.target)))
            return <g key={edge.id} className={pathActive ? 'twin-edge is-highlighted' : 'twin-edge'}><path d={`M ${start.x + 13} ${start.y} C ${(start.x + end.x) / 2} ${start.y}, ${(start.x + end.x) / 2} ${end.y}, ${end.x - 14} ${end.y}`} /><title>{`${edge.type} · ${edge.source} → ${edge.target}`}</title></g>
          })}
          {visibleNodes.map((node) => {
            const position = nodePositions[node.id]
            if (!position) return null
            const selectedNode = selectedId === node.id
            return <g key={node.id} className={`twin-graph-node ${selectedNode ? 'is-selected' : ''}`} transform={`translate(${position.x} ${position.y})`} onPointerDown={(event) => graphPointerDown(event, node.id)} onClick={() => setSelectedId(node.id)}>
              <Shape type={node.type} fill={nodeColor(node)} />
              <text y="30" textAnchor="middle">{node.name.length > 21 ? `${node.name.slice(0, 20)}…` : node.name}</text>
              <title>{`${node.type.replaceAll('_', ' ')} · ${node.name} · ${node.status} · ${node.risk_level}`}</title>
            </g>
          })}
        </svg> : <div className="twin-empty-state"><strong>No matching graph entities</strong><span>Change the filters or add supply-chain records.</span></div>}
      </div>
      <div className="twin-graph-footer"><span>{visibleNodes.length} shown · {graph.nodes.length} loaded · {totalNodes} matching records · {graph.graph_counts?.edges ?? graph.edges.length} relationships</span>
        {currentPage < pageCount && <button type="button" className="secondary-button" disabled={pageLoading} onClick={loadNextPage}>{pageLoading ? 'Loading…' : `Load next 100 of ${totalNodes}`}</button>}
        {pageError && <small className="twin-error-text">{pageError}</small>}
      </div>
    </section>

    <div className="twin-two-column">
      <section className="panel twin-panel">
        <div className="panel-heading twin-map-heading"><div><p className="eyebrow">GEOGRAPHIC VIEW</p><h2>Facilities, shipments, and active hazards</h2><p>Only recorded coordinates and current GDACS source geometry are plotted.</p></div><div className="twin-map-filter-controls"><input aria-label="Search mapped locations" value={geoSearch} onChange={(event) => setGeoSearch(event.target.value)} placeholder="Find a mapped record…" /><select aria-label="Filter mapped entity type" value={geoTypeFilter} onChange={(event) => setGeoTypeFilter(event.target.value)}><option value="all">All map features</option><option value="supplier">Suppliers</option><option value="warehouse">Warehouses</option><option value="material">Materials</option><option value="shipment">Shipments</option><option value="disruption">Disruptions</option></select></div><span className="twin-map-count">{visibleGeoFeatures.length} / {data?.geo?.counts?.features ?? 0} mapped</span></div>
        <TwinMap geo={data?.geo ? { ...data.geo, features: visibleGeoFeatures } : null} onAnalyze={analyzeImpact} />
        <p className="twin-map-caption">OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors. Shipment lines connect recorded endpoints and are not verified carrier routes. {generatedAt ? `Data snapshot ${formatDate(generatedAt, true)}.` : ''}</p>
      </section>
      <section className="panel twin-panel twin-detail-section">
        <div className="panel-heading"><div><p className="eyebrow">ENTITY INSPECTOR</p><h2>Selected record</h2></div></div>
        {detailError && <p className="twin-error-text">{detailError}</p>}
        <EntityPanel node={selected} detail={selectedDetail} busy={impactBusy} onAnalyze={analyzeImpact} />
      </section>
    </div>

    {impact && <section className="panel twin-panel twin-impact-panel">
      <div className="panel-heading"><div><p className="eyebrow">IMPACT ANALYSIS · {impact.disruption?.severity}</p><h2>{impact.disruption?.title}</h2><p>Records are classified with a reason; geographic thresholds are policy distances, not observed hazard boundaries.</p></div><button type="button" className="secondary-button" onClick={() => setImpact(null)}>Close</button></div>
      <div className="twin-classification-counts">{Object.entries(impact.counts || {}).map(([key, value]) => <span className={`classification-${key}`} key={key}><b>{value}</b>{key.replaceAll('_', ' ')}</span>)}</div>
      <div className="twin-impact-method">{impact.method?.geographic_source || 'Geographic source unavailable'} · {impact.method?.threshold_km} km {impact.method?.threshold_policy} threshold · country/region-name matching disabled</div>
      <div className="twin-impact-list">{impact.entities?.filter((item) => item.classification !== 'unaffected').slice(0, 30).map((item) => <article key={item.id}><span className={`impact-marker classification-${item.classification}`} /> <div><strong>{item.name}</strong><small>{item.type.replaceAll('_', ' ')} · {item.classification.replaceAll('_', ' ')}</small><p>{item.reason}</p></div></article>)}</div>
    </section>}

    <section className="panel twin-panel twin-simulation-panel">
      <div className="panel-heading"><div><p className="eyebrow">WHAT-IF WORKSPACE</p><h2>Run an isolated scenario</h2><p>Results are saved as simulation records. ARES operational records are read-only during this calculation.</p></div><span className="simulated-badge">SIMULATED</span></div>
      <form className="twin-simulation-form" onSubmit={runSimulation}>
        <label>Scenario<select value={scenarioType} onChange={(event) => setScenarioType(event.target.value)}>{SCENARIOS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>Entity<select required value={scenarioEntity} onChange={(event) => setScenarioEntity(event.target.value)}>{scenarioEntities.map((node) => <option key={node.entity_id} value={node.entity_id}>{node.name}</option>)}</select></label>
        <label>Horizon (days)<input type="number" min="1" max="365" value={horizonDays} onChange={(event) => setHorizonDays(event.target.value)} /></label>
        {(scenarioType === 'shipment_delay' || scenarioType === 'route_disruption') && <label>Delay (days)<input type="number" min="1" max="365" value={scenarioValue} onChange={(event) => setScenarioValue(event.target.value)} /></label>}
        {scenarioType === 'material_shortage' && <label>Shortage quantity<input type="number" min="0" step="0.01" value={scenarioValue} onChange={(event) => setScenarioValue(event.target.value)} /></label>}
        {scenarioType === 'demand_surge' && <label>Demand increase (%)<input type="number" min="0" max="1000" step="0.01" value={scenarioValue} onChange={(event) => setScenarioValue(event.target.value)} /></label>}
        <button className="primary-button" type="submit" disabled={simulationBusy || !scenarioEntity}>{simulationBusy ? 'Simulating…' : 'Run scenario'}</button>
      </form>
      {scenarioType === 'demand_surge' && <p className="twin-data-note">Demand uplift is quantified only when the selected material has at least 60 days of movement history and 10 distinct issue dates.</p>}
      {simulation && <div className="twin-simulation-result">
        <div className="twin-result-heading"><div><span className="simulated-badge">SIMULATED</span><strong>{simulation.result?.summary?.affected_materials ?? 0} materials in scope</strong></div><small>Saved {formatDate(simulation.created_at, true)} · ID {simulation.id}</small></div>
        <div className="twin-impact-summary">{simulation.result?.summary?.purchase_orders_in_scope ?? 0} purchase orders · {simulation.result?.summary?.shipments_in_scope ?? 0} shipments · projected through {simulation.result?.horizon_end}</div>
        {simulation.result?.delayed_purchase_orders?.length > 0 && <div className="twin-delay-list"><strong>Delayed purchase orders</strong>{simulation.result.delayed_purchase_orders.map((item) => <span key={item.purchase_order}>{item.purchase_order}: {item.baseline_eta} → {item.simulated_eta}{item.deferred_beyond_horizon ? ' · beyond horizon' : ''}</span>)}</div>}
        {simulation.result?.material_projection?.map((item) => <article className="twin-material-comparison" key={item.material_id}><div><strong>{item.sku} · {item.name}</strong><span>Baseline available: {item.baseline.projected_available ?? item.baseline.supply_only_available ?? 'insufficient data'} {item.unit}</span><b>Simulated available: {item.simulated.projected_available ?? item.simulated.supply_only_available ?? 'insufficient data'} {item.unit}</b><small>{item.consequence}</small></div></article>)}
        {simulation.result?.assumptions_and_data_gaps?.map((note) => <p className="twin-data-note" key={note}>{note}</p>)}
      </div>}
    </section>
    {pageError && <div className="feedback-banner error-banner" role="alert">{pageError}</div>}
    {loading && !data && <div className="twin-page-loading"><i />Loading the current ARES digital twin…</div>}
    {data?.sync?.pending_delivery_count > 0 && <p className="twin-pending-note">{data.sync.pending_delivery_count} live invalidation event(s) await retry; recovery polling remains available. Latest change {syncLabel}.</p>}
  </div>
}
