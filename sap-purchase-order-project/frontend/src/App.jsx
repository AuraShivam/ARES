import { useCallback, useEffect, useMemo, useState } from 'react'

const API = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/$/, '')

const NAV_GROUPS = [
  {
    title: 'Monitor',
    items: [
      ['overview', 'Overview', '◫'],
      ['disruptions', 'Disruptions', '⌁'],
      ['shipments', 'Shipments', '⇢'],
    ],
  },
  {
    title: 'Operations',
    items: [
      ['purchase-orders', 'Purchase orders', '▤'],
      ['inventory', 'Inventory', '▦'],
      ['warehouses', 'Warehouses', '⌂'],
      ['suppliers', 'Suppliers', '♧'],
      ['materials', 'Materials', '◇'],
    ],
  },
  {
    title: 'Records',
    items: [
      ['purchase-order-lines', 'PO line items', '≡'],
      ['inventory-movements', 'Stock movements', '↕'],
      ['audit-events', 'Audit history', '◷'],
    ],
  },
]

const SECTIONS = {
  overview: { title: 'Network overview', description: 'A live view of supply-chain exposure and operational signals.' },
  disruptions: { title: 'Disruptions', description: 'Review events, assess exposure, and record a response.' },
  shipments: { title: 'Shipments', description: 'Track shipment status, routes, and delivery risk.' },
  'purchase-orders': { title: 'Purchase orders', description: 'Review supplier commitments and multi-line order value.' },
  inventory: { title: 'Inventory', description: 'See on-hand stock, reorder thresholds, and warehouse balances.' },
  warehouses: { title: 'Warehouses', description: 'Manage the facilities connected to inventory balances.' },
  suppliers: { title: 'Suppliers', description: 'Review supplier coverage, lead times, and risk profiles.' },
  materials: { title: 'Materials', description: 'Explore material criticality and preferred sourcing.' },
  'purchase-order-lines': { title: 'PO line items', description: 'Inspect the materials and quantities behind each order.' },
  'inventory-movements': { title: 'Stock movements', description: 'Review receipts, issues, and inventory adjustments.' },
  'audit-events': { title: 'Audit history', description: 'See before-and-after snapshots for API changes.' },
}

const TABLE_COLUMNS = {
  disruptions: [
    ['title', 'Event'], ['disruption_type', 'Type'], ['affected_region', 'Region'],
    ['severity', 'Severity'], ['affected_supplier_name', 'Supplier'], ['status', 'Status'],
    ['created_at', 'Reported'], ['assess', ''],
  ],
  shipments: [
    ['reference', 'Reference'], ['purchase_order_number', 'Purchase order'], ['origin', 'Origin'],
    ['destination', 'Destination'], ['eta', 'ETA'], ['risk_score', 'Risk'], ['status', 'Status'],
  ],
  'purchase-orders': [
    ['number', 'PO number'], ['supplier_name', 'Supplier'], ['line_count', 'Lines'],
    ['expected_date', 'Expected'], ['status', 'Status'], ['total_value', 'Total value'],
  ],
  inventory: [
    ['material_sku', 'SKU'], ['material_name', 'Material'], ['warehouse_name', 'Warehouse'],
    ['location', 'Location'], ['quantity', 'On hand'], ['reorder_point', 'Reorder at'], ['below_reorder_point', 'Signal'],
  ],
  warehouses: [
    ['code', 'Code'], ['name', 'Warehouse'], ['region', 'Region'], ['country', 'Country'],
    ['warehouse_type', 'Type'], ['active', 'Status'],
  ],
  suppliers: [
    ['code', 'Code'], ['name', 'Supplier'], ['region', 'Region'], ['country', 'Country'],
    ['lead_time_days', 'Lead time'], ['risk_score', 'Risk profile'], ['status', 'Status'],
  ],
  materials: [
    ['sku', 'SKU'], ['name', 'Material'], ['category', 'Category'],
    ['criticality', 'Criticality'], ['preferred_supplier_name', 'Preferred supplier'],
  ],
  'purchase-order-lines': [
    ['purchase_order', 'PO reference'], ['line_number', 'Line'], ['material_sku', 'SKU'],
    ['material_name', 'Material'], ['quantity', 'Ordered'], ['received_quantity', 'Received'], ['line_total', 'Line value'],
  ],
  'inventory-movements': [
    ['material_sku', 'SKU'], ['warehouse_name', 'Warehouse'], ['movement_type', 'Movement'],
    ['quantity_delta', 'Change'], ['balance_after', 'Balance after'], ['reference', 'Reference'], ['actor', 'Actor'], ['created_at', 'Recorded'],
  ],
  'audit-events': [
    ['entity_type', 'Record type'], ['action', 'Action'], ['entity_id', 'Record ID'],
    ['actor', 'Actor'], ['created_at', 'Changed'], ['changes', 'Details'],
  ],
}

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
const STATUS_LABELS = { review: 'Under review', in_transit: 'In transit', at_risk: 'At risk' }
const humanize = (value = '') => STATUS_LABELS[value] || String(value).replaceAll('_', ' ')
const rowsFrom = (payload) => Array.isArray(payload) ? payload : Array.isArray(payload?.results) ? payload.results : []

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? numberFormat.format(number) : String(value)
}

function formatDate(value, includeTime = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, includeTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(date)
}

function compactId(value) {
  return typeof value === 'string' && value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value || '—'
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  let response
  try {
    response = await fetch(`${API}${path}`, { ...options, headers })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Could not reach the ARES API. Start Django and check the API URL.')
  }

  const bodyText = await response.text()
  let payload = null
  if (bodyText) {
    try { payload = JSON.parse(bodyText) } catch { payload = null }
  }
  if (!response.ok) {
    let message = payload?.detail
    if (!message && payload && typeof payload === 'object') {
      message = Object.entries(payload)
        .map(([key, value]) => `${humanize(key)}: ${Array.isArray(value) ? value.join(', ') : String(value)}`)
        .join(' · ')
    }
    throw new Error(message || `The API returned HTTP ${response.status}.`)
  }
  return payload
}

function App() {
  const [section, setSection] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [apiHealth, setApiHealth] = useState(null)
  const [records, setRecords] = useState([])
  const [homeData, setHomeData] = useState({ disruptions: [], shipments: [], inventory: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [assessment, setAssessment] = useState(null)
  const [busyId, setBusyId] = useState('')
  const [saving, setSaving] = useState(false)
  const [modal, setModal] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState({ key: '', direction: 'asc' })
  const [lastUpdated, setLastUpdated] = useState(null)

  const refresh = useCallback(async (signal) => {
    setLoading(true)
    setError('')
    try {
      const [summary, health] = await Promise.all([
        request('/overview/', { signal }),
        request('/health/', { signal }),
      ])
      setOverview(summary)
      setApiHealth(health)

      if (section === 'overview') {
        const [disruptions, shipments, inventory] = await Promise.all([
          request('/disruptions/', { signal }),
          request('/shipments/', { signal }),
          request('/inventory/', { signal }),
        ])
        setHomeData({ disruptions: rowsFrom(disruptions), shipments: rowsFrom(shipments), inventory: rowsFrom(inventory) })
      } else {
        const data = await request(`/${section}/`, { signal })
        setRecords(rowsFrom(data))
      }
      setLastUpdated(new Date())
    } catch (requestError) {
      if (requestError.name !== 'AbortError') setError(requestError.message)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [section])

  useEffect(() => {
    const controller = new AbortController()
    refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  useEffect(() => {
    if (!notice) return undefined
    const timer = window.setTimeout(() => setNotice(''), 4500)
    return () => window.clearTimeout(timer)
  }, [notice])

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === 'Escape') {
        setModal('')
        setAssessment(null)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  function navigate(nextSection) {
    setSection(nextSection)
    setSearch('')
    setSort({ key: '', direction: 'asc' })
    setAssessment(null)
  }

  async function assessRisk(disruptionId) {
    setBusyId(disruptionId)
    setAssessment(null)
    setError('')
    try {
      setAssessment(await request('/risk/assess/', { method: 'POST', body: JSON.stringify({ disruption_id: disruptionId }) }))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusyId('')
    }
  }

  async function markReviewed(disruptionId) {
    try {
      await request(`/disruptions/${disruptionId}/`, { method: 'PATCH', body: JSON.stringify({ status: 'review' }) })
      setAssessment(null)
      setNotice('Disruption marked as under review.')
      await refresh()
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function createDisruption(payload) {
    setSaving(true)
    try {
      const created = await request('/disruptions/', { method: 'POST', body: JSON.stringify(payload) })
      setModal('')
      navigate('disruptions')
      setNotice('Disruption created. Preparing its assessment brief…')
      try {
        const [disruptions, summary] = await Promise.all([request('/disruptions/'), request('/overview/')])
        setRecords(rowsFrom(disruptions))
        setOverview(summary)
        setLastUpdated(new Date())
      } catch (requestError) {
        setError(`Disruption created, but the list could not refresh: ${requestError.message}`)
      }
      try {
        setAssessment(await request('/risk/assess/', { method: 'POST', body: JSON.stringify({ disruption_id: created.id }) }))
      } catch (requestError) {
        setError(`Disruption created, but assessment failed: ${requestError.message}`)
      }
    } finally {
      setSaving(false)
    }
  }

  async function recordMovement(payload) {
    setSaving(true)
    try {
      await request('/inventory-movements/', { method: 'POST', body: JSON.stringify(payload) })
      setModal('')
      setNotice('Stock movement recorded and inventory balance updated.')
      navigate('inventory-movements')
    } finally {
      setSaving(false)
    }
  }

  async function createPurchaseOrder(payload) {
    setSaving(true)
    try {
      await request('/purchase-orders/', { method: 'POST', body: JSON.stringify(payload) })
      setModal('')
      setNotice('Purchase order created.')
      await refresh()
    } finally {
      setSaving(false)
    }
  }

  const current = SECTIONS[section] || SECTIONS.overview
  const columns = TABLE_COLUMNS[section] || []
  const visibleRecords = useMemo(() => {
    const query = search.trim().toLowerCase()
    let result = records
    if (query) {
      result = result.filter((record) => JSON.stringify(record).toLowerCase().includes(query))
    }
    if (sort.key) {
      result = [...result].sort((left, right) => {
        const a = left[sort.key] ?? ''
        const b = right[sort.key] ?? ''
        const numberA = Number(a)
        const numberB = Number(b)
        const comparison = a !== '' && b !== '' && Number.isFinite(numberA) && Number.isFinite(numberB)
          ? numberA - numberB
          : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
        return sort.direction === 'asc' ? comparison : -comparison
      })
    }
    return result
  }, [records, search, sort])

  const action = section === 'inventory'
    ? { label: 'Record movement', icon: '＋', modal: 'movement' }
    : section === 'purchase-orders'
      ? { label: 'New purchase order', icon: '＋', modal: 'purchase-order' }
      : section === 'overview' || section === 'disruptions'
        ? { label: 'New disruption', icon: '＋', modal: 'disruption' }
        : null

  function toggleSort(key) {
    setSort((currentSort) => ({
      key,
      direction: currentSort.key === key && currentSort.direction === 'asc' ? 'desc' : 'asc',
    }))
  }

  function exportCsv() {
    const rows = [columns.filter(([key]) => key !== 'assess').map(([, title]) => title)]
    visibleRecords.forEach((record) => {
      rows.push(columns.filter(([key]) => key !== 'assess').map(([key]) => {
        const value = key === 'line_count' ? record.lines?.length : record[key]
        const text = value && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')
        return /^[=+\-@]/.test(text) ? `'${text}` : text
      }))
    })
    const csv = rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(',')).join('\r\n')
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `ares-${section}-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" onClick={(event) => { event.preventDefault(); navigate('overview') }}>
          <span className="brand-mark">A</span>
          <span className="brand-copy"><strong>ARES</strong><small>SUPPLY CHAIN INTELLIGENCE</small></span>
        </a>
        <div className="workspace-pill"><span className="workspace-dot" /> <span>DEMO NETWORK</span><span className="workspace-chevron">⌄</span></div>
        <nav className="navigation" aria-label="Main navigation">
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.title}>
              <p className="nav-caption">{group.title}</p>
              {group.items.map(([key, title, icon]) => (
                <button
                  aria-current={section === key ? 'page' : undefined}
                  className={`nav-item ${section === key ? 'selected' : ''}`}
                  key={key}
                  onClick={() => navigate(key)}
                  title={title}
                >
                  <span className="nav-icon" aria-hidden="true">{icon}</span>
                  <span>{title}</span>
                  {key === 'disruptions' && overview?.open_disruptions > 0 && <span className="nav-count">{overview.open_disruptions}</span>}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className={`connection-light ${apiHealth?.status === 'ok' ? 'is-online' : ''}`} />
          <span className="connection-copy"><strong>{apiHealth?.status === 'ok' ? 'API connected' : 'API connection'}</strong><small>{apiHealth?.database || 'Waiting for backend'}</small></span>
          <span className="api-tag">LOCAL</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>ARES</span><i>/</i><strong>{current.title}</strong></div>
          <div className="topbar-actions">
            <span className={`api-status ${apiHealth?.status === 'ok' ? 'connected' : ''}`}><i />{apiHealth?.status === 'ok' ? 'API connected' : 'Connecting'}</span>
            <button className="icon-button refresh-button" aria-label="Refresh dashboard" onClick={() => refresh()} disabled={loading}>↻</button>
            <div className="avatar" aria-label="Local demo user">SC</div>
          </div>
        </header>

        <section className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">AUTONOMOUS RESILIENT ENTERPRISE SUPPLY CHAIN</p>
              <h1>{current.title}</h1>
              <p className="page-description">{current.description}</p>
            </div>
            <div className="heading-actions">
              <div className="updated-chip"><span className="pulse-dot" />{lastUpdated ? `Updated ${new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(lastUpdated)}` : 'Local snapshot'}</div>
              {action && <button className="primary-button" onClick={() => setModal(action.modal)}><span aria-hidden="true">{action.icon}</span>{action.label}</button>}
            </div>
          </div>

          {error && <div className="feedback-banner error-banner" role="alert"><span className="feedback-icon">!</span><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
          {notice && <div className="feedback-banner success-banner" role="status"><span className="feedback-icon">✓</span><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice('')}>×</button></div>}

          {section === 'overview'
            ? <OverviewPage data={overview} homeData={homeData} loading={loading} apiHealth={apiHealth} onNavigate={navigate} onAssess={assessRisk} busyId={busyId} />
            : <section className="panel records-panel">
              <div className="records-heading">
                <div><h2>{current.title}</h2><p>{records.length} {records.length === 1 ? 'record' : 'records'} in the local dataset</p></div>
                {loading && <span className="loading-inline"><i />Refreshing</span>}
              </div>
              {loading && records.length === 0
                ? <LoadingState />
                : <DataTable
                  section={section}
                  columns={columns}
                  records={visibleRecords}
                  total={records.length}
                  search={search}
                  onSearch={setSearch}
                  sort={sort}
                  onSort={toggleSort}
                  onExport={exportCsv}
                  onAssess={assessRisk}
                  busyId={busyId}
                />}
            </section>}

          <footer className="page-footer"><span>ARES · LOCAL HACKFEST DEMO</span><span>Recommendations are advisory and require human review.</span></footer>
        </section>
      </main>

      {modal === 'disruption' && <DisruptionForm onClose={() => setModal('')} onSubmit={createDisruption} saving={saving} />}
      {modal === 'movement' && <MovementForm onClose={() => setModal('')} onSubmit={recordMovement} saving={saving} />}
      {modal === 'purchase-order' && <PurchaseOrderForm onClose={() => setModal('')} onSubmit={createPurchaseOrder} saving={saving} />}
      {assessment && <AssessmentModal result={assessment} onClose={() => setAssessment(null)} onMarkReviewed={markReviewed} />}
    </div>
  )
}

function OverviewPage({ data, homeData, loading, apiHealth, onNavigate, onAssess, busyId }) {
  const cards = [
    { label: 'Suppliers', value: data?.suppliers, note: 'in the partner network', icon: '♧', tone: 'teal' },
    { label: 'Purchase orders', value: data?.purchase_orders, note: 'orders on record', icon: '▤', tone: 'blue' },
    { label: 'At-risk shipments', value: data?.at_risk_shipments, note: 'delayed or need review', icon: '⇢', tone: 'amber' },
    { label: 'Open disruptions', value: data?.open_disruptions, note: 'awaiting response', icon: '⌁', tone: 'red' },
  ]
  const priorityDisruptions = homeData.disruptions.filter((item) => item.status !== 'resolved').sort((a, b) => severityWeight(b.severity) - severityWeight(a.severity)).slice(0, 4)
  const atRiskShipments = homeData.shipments.filter((shipment) => ['delayed', 'at_risk'].includes(shipment.status)).slice(0, 4)
  const lowInventory = homeData.inventory.filter((balance) => balance.below_reorder_point).slice(0, 4)

  return <>
    <div className="metric-grid">
      {cards.map((card) => <article className="metric-card" key={card.label}>
        <div className="metric-top"><span>{card.label}</span><span className={`metric-icon ${card.tone}`}>{card.icon}</span></div>
        <strong>{loading && card.value == null ? '—' : formatNumber(card.value)}</strong>
        <small>{card.note}</small>
      </article>)}
    </div>

    <div className="overview-grid">
      <section className="panel response-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">HUMAN REVIEW QUEUE</p><h2>Priority disruptions</h2><p>Highest-severity events first</p></div>
          <button className="text-button" onClick={() => onNavigate('disruptions')}>All disruptions <span>→</span></button>
        </div>
        {loading && homeData.disruptions.length === 0 ? <LoadingState compact /> : <DisruptionQueue items={priorityDisruptions} onAssess={onAssess} busyId={busyId} />}
      </section>

      <section className="panel signal-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">OPERATING SIGNALS</p><h2>Network watch</h2><p>Current exposure indicators</p></div>
          <span className={`watch-status ${data?.open_disruptions || data?.at_risk_shipments ? 'watch' : 'clear'}`}><i />{data?.open_disruptions || data?.at_risk_shipments ? 'ATTENTION' : 'CLEAR'}</span>
        </div>
        <div className="signal-list">
          <SignalRow name="Inventory at or below reorder" value={data?.low_inventory} tone="amber" onClick={() => onNavigate('inventory')} />
          <SignalRow name="Delayed / at-risk shipments" value={data?.at_risk_shipments} tone="red" onClick={() => onNavigate('shipments')} />
          <SignalRow name="Open disruption events" value={data?.open_disruptions} tone="blue" onClick={() => onNavigate('disruptions')} />
        </div>
        <div className="connection-card">
          <span className={`connection-icon ${apiHealth?.status === 'ok' ? 'ok' : ''}`}>{apiHealth?.status === 'ok' ? '✓' : '!'}</span>
          <div><strong>Data connection</strong><small>{apiHealth?.database || 'Waiting for API status'}</small></div>
          <span className={`connection-label ${apiHealth?.status === 'ok' ? 'ok' : ''}`}>{apiHealth?.status === 'ok' ? 'CONNECTED' : 'OFFLINE'}</span>
        </div>
      </section>
    </div>

    <div className="overview-bottom">
      <section className="panel compact-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">LOGISTICS</p><h2>Shipments to watch</h2></div>
          <button className="text-button" onClick={() => onNavigate('shipments')}>View shipments <span>→</span></button>
        </div>
        {atRiskShipments.length
          ? <div className="mini-list">{atRiskShipments.map((shipment) => <div className="mini-row" key={shipment.id}>
            <span className={`mini-marker ${shipment.status === 'delayed' ? 'is-red' : 'is-amber'}`} />
            <span className="mini-main"><strong>{shipment.reference}</strong><small>{shipment.origin} <b>→</b> {shipment.destination}</small></span>
            <span className="mini-meta"><strong>{formatDate(shipment.eta)}</strong><small>{humanize(shipment.status)}</small></span>
          </div>)}</div>
          : <InlineEmpty loading={loading} text="No at-risk shipments" detail="Shipment exceptions will appear here." />}
      </section>

      <section className="panel compact-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">STOCK HEALTH</p><h2>Reorder watch</h2></div>
          <button className="text-button" onClick={() => onNavigate('inventory')}>View stock <span>→</span></button>
        </div>
        {lowInventory.length
          ? <div className="mini-list">{lowInventory.map((balance) => <div className="mini-row" key={balance.id}>
            <span className="mini-marker is-amber" />
            <span className="mini-main"><strong>{balance.material_sku} · {balance.material_name}</strong><small>{balance.warehouse_name || balance.location}</small></span>
            <span className="mini-meta"><strong>{formatNumber(balance.quantity)}</strong><small>reorder {formatNumber(balance.reorder_point)}</small></span>
          </div>)}</div>
          : <InlineEmpty loading={loading} text="No low-stock signals" detail="Balances at or below reorder point appear here." />}
      </section>
    </div>

    <section className="panel network-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">NETWORK FOOTPRINT</p><h2>Connected supply chain</h2></div>
        <span className="demo-label">LOCAL DEMO DATA</span>
      </div>
      <div className="network-flow">
        <NetworkNode icon="♧" title="Suppliers" value={data?.suppliers} onClick={() => onNavigate('suppliers')} />
        <span className="flow-connector" aria-hidden="true" />
        <NetworkNode icon="◇" title="Materials" value={data?.materials} onClick={() => onNavigate('materials')} />
        <span className="flow-connector" aria-hidden="true" />
        <NetworkNode icon="▤" title="Orders" value={data?.purchase_orders} onClick={() => onNavigate('purchase-orders')} />
        <span className="flow-connector" aria-hidden="true" />
        <NetworkNode icon="⌂" title="Warehouses" value={data?.warehouses} onClick={() => onNavigate('warehouses')} />
        <span className="flow-connector" aria-hidden="true" />
        <NetworkNode icon="⇢" title="Shipments" value={data?.at_risk_shipments} caption="at risk" tone="risk" onClick={() => onNavigate('shipments')} />
      </div>
    </section>
  </>
}

function severityWeight(severity) {
  return ({ critical: 4, high: 3, medium: 2, low: 1 })[severity] || 0
}

function SignalRow({ name, value, tone, onClick }) {
  return <button className="signal-row" onClick={onClick}><span><i className={`signal-dot ${tone}`} />{name}</span><strong>{formatNumber(value)}</strong><span className="signal-chevron">›</span></button>
}

function DisruptionQueue({ items, onAssess, busyId }) {
  if (!items.length) return <InlineEmpty text="No open disruption events" detail="New events will appear in this queue." />
  return <div className="queue-list">{items.map((item) => <article className="queue-item" key={item.id}>
    <span className={`severity-dot severity-${item.severity}`} />
    <div className="queue-main"><strong>{item.title}</strong><span>{item.affected_region || 'Region not specified'} · {item.affected_supplier_name || humanize(item.disruption_type)}</span></div>
    <StatusBadge value={item.severity} />
    <button className="assess-button" onClick={() => onAssess(item.id)} disabled={busyId === item.id}>{busyId === item.id ? 'Scoring…' : 'Assess'}</button>
  </article>)}</div>
}

function NetworkNode({ icon, title, value, caption = 'records', tone = '', onClick }) {
  return <button className={`network-node ${tone}`} onClick={onClick}>
    <span className="network-node-icon">{icon}</span><strong>{title}</strong><small><b>{formatNumber(value)}</b> {caption}</small>
  </button>
}

function InlineEmpty({ loading = false, text, detail }) {
  if (loading) return <div className="inline-empty"><span className="spinner" /><small>Loading local data…</small></div>
  return <div className="inline-empty"><strong>{text}</strong><small>{detail}</small></div>
}

function LoadingState({ compact = false }) {
  return <div className={`loading-state ${compact ? 'compact' : ''}`} role="status"><span className="spinner" /><span>Loading ARES data…</span></div>
}

function DataTable({ section, columns, records, total, search, onSearch, sort, onSort, onExport, onAssess, busyId }) {
  return <>
    <div className="table-toolbar">
      <label className="search-field"><span aria-hidden="true">⌕</span><input aria-label={`Search ${SECTIONS[section].title}`} placeholder={`Search ${SECTIONS[section].title.toLowerCase()}…`} value={search} onChange={(event) => onSearch(event.target.value)} /></label>
      <div className="table-tools"><span className="row-count">Showing <strong>{records.length}</strong> of {total}</span><button className="secondary-button export-button" onClick={onExport} disabled={!records.length}><span>↓</span> Export CSV</button></div>
    </div>
    {records.length === 0
      ? <div className="table-empty"><span>{search ? '⌕' : '▤'}</span><strong>{search ? 'No matching records' : 'No records yet'}</strong><small>{search ? 'Try a different search term.' : 'Seed the local database to load the ARES demo network.'}</small></div>
      : <div className="table-scroll"><table className="data-table">
        <thead><tr>{columns.map(([key, title]) => <th key={key}>{title ? <button className="sort-button" onClick={() => onSort(key)}>{title}<span>{sort.key === key ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ' ↕'}</span></button> : 'Action'}</th>)}</tr></thead>
        <tbody>{records.map((record) => <tr key={record.id}>{columns.map(([key]) => <td key={key}>
          {key === 'assess'
            ? <button className="assess-button table-assess" onClick={() => onAssess(record.id)} disabled={busyId === record.id}>{busyId === record.id ? 'Scoring…' : 'Assess risk'}</button>
            : <TableCell section={section} field={key} record={record} />}
        </td>)}</tr>)}</tbody>
      </table></div>}
  </>
}

function TableCell({ section, field, record }) {
  if (field === 'line_count') return <span className="count-cell">{record.lines?.length ?? 0} <small>lines</small></span>
  if (field === 'changes') return <details className="change-details"><summary>View snapshot</summary><pre>{JSON.stringify(record.changes, null, 2)}</pre></details>
  const value = record[field]
  if (value === null || value === undefined || value === '') return <span className="muted-cell">—</span>
  if (['status', 'severity', 'criticality', 'movement_type', 'action', 'warehouse_type'].includes(field)) return <StatusBadge value={value} />
  if (field === 'active' || field === 'below_reorder_point') return <StatusBadge value={field === 'active' ? (value ? 'active' : 'inactive') : (value ? 'reorder' : 'healthy')} />
  if (['eta', 'expected_date'].includes(field)) return formatDate(value)
  if (field === 'created_at' || field === 'updated_at') return formatDate(value, true)
  if (field === 'entity_id' || field === 'purchase_order') return <span className="mono-cell" title={value}>{compactId(value)}</span>
  if (field === 'risk_score') return <span className={`risk-value ${Number(value) >= 60 ? 'high' : Number(value) >= 35 ? 'medium' : ''}`}>{formatNumber(value)}<small>/100</small></span>
  if (field === 'confidence') return `${formatNumber(value)}%`
  if (field === 'lead_time_days') return `${formatNumber(value)} days`
  if (field === 'quantity_delta') return <span className={Number(value) < 0 ? 'delta-negative' : 'delta-positive'}>{Number(value) > 0 ? '+' : ''}{formatNumber(value)}</span>
  if (field === 'total_value' || field === 'line_total') return <strong className="money-cell">{record.currency ? `${record.currency} ` : ''}{formatNumber(value)}</strong>
  if (field === 'quantity' || field === 'received_quantity' || field === 'reorder_point' || field === 'balance_after') return formatNumber(value)
  if (field === 'line_number') return <span className="line-number">{String(value).padStart(2, '0')}</span>
  if (field === 'entity_type') return <span className="mono-cell">{humanize(value)}</span>
  return <span className={['number', 'risk_score'].includes(field) ? 'number-cell' : ''}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
}

function StatusBadge({ value }) {
  const normalized = String(value).toLowerCase().replaceAll(' ', '_')
  return <span className={`status-badge status-${normalized}`}><i />{humanize(value)}</span>
}

function AssessmentModal({ result, onClose, onMarkReviewed }) {
  const [reviewing, setReviewing] = useState(false)
  async function markReviewed() {
    setReviewing(true)
    try { await onMarkReviewed(result.disruption_id) } finally { setReviewing(false) }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="dialog assessment-dialog" role="dialog" aria-modal="true" aria-labelledby="assessment-title">
      <div className="dialog-header"><div><p className="eyebrow">ARES RISK ASSESSMENT</p><h2 id="assessment-title">Disruption response brief</h2></div><button className="icon-button" aria-label="Close assessment" onClick={onClose}>×</button></div>
      <div className="risk-summary"><div className="risk-number"><strong>{formatNumber(result.risk_score)}</strong><small>/ 100</small></div><div><StatusBadge value={result.risk_band} /><p>{formatNumber(result.confidence)}% evidence confidence</p></div><span className="model-tag">{result.model || 'Rules v1'}</span></div>
      <h3>Why this score</h3><ul className="factor-list">{(result.factors || []).map((factor, index) => <li key={`${factor}-${index}`}>{factor}</li>)}</ul>
      <div className="recommendation-card"><span>✦</span><div><strong>Suggested response</strong><p>{result.recommendation}</p></div></div>
      <div className="governance-note">{result.governance || 'Advisory only. A human must review and approve operational actions.'}</div>
      <div className="dialog-actions"><button className="secondary-button" onClick={onClose}>Close brief</button><button className="primary-button" onClick={markReviewed} disabled={reviewing}>{reviewing ? 'Saving…' : 'Mark under review'}</button></div>
    </section>
  </div>
}

function FormDialog({ title, eyebrow, description, onClose, onSubmit, saving, children, submitLabel = 'Save record' }) {
  const [formError, setFormError] = useState('')
  async function handleSubmit(event) {
    event.preventDefault()
    setFormError('')
    try { await onSubmit(event) } catch (error) { setFormError(error.message) }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="dialog form-dialog" role="dialog" aria-modal="true" aria-labelledby="form-title">
      <div className="dialog-header"><div><p className="eyebrow">{eyebrow}</p><h2 id="form-title">{title}</h2><p className="dialog-description">{description}</p></div><button type="button" className="icon-button" aria-label="Close form" onClick={onClose}>×</button></div>
      <form onSubmit={handleSubmit}>
        <div className="form-fields">{children}</div>
        {formError && <div className="form-error" role="alert">{formError}</div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={saving}>Cancel</button><button type="submit" className="primary-button" disabled={saving}>{saving ? 'Saving…' : submitLabel}</button></div>
      </form>
    </section>
  </div>
}

function Field({ label, name, children, hint, className = '' }) {
  return <label className={`form-field ${className}`}><span className="field-label">{label}</span>{children}{hint && <small className="field-hint">{hint}</small>}</label>
}

function DisruptionForm({ onClose, onSubmit, saving }) {
  const [suppliers, setSuppliers] = useState([])
  const [lookupError, setLookupError] = useState('')
  useEffect(() => { request('/suppliers/').then((payload) => setSuppliers(rowsFrom(payload))).catch((error) => setLookupError(error.message)) }, [])
  return <FormDialog title="Report a disruption" eyebrow="OPERATIONAL EVENT" description="Capture a supply-chain event, then review its explainable risk assessment." onClose={onClose} onSubmit={(event) => {
    const form = new FormData(event.currentTarget)
    const payload = Object.fromEntries(form.entries())
    payload.confidence = Number(payload.confidence)
    if (!payload.affected_supplier) delete payload.affected_supplier
    return onSubmit(payload)
  }} saving={saving} submitLabel="Create and assess">
    <Field label="Event title" name="title" className="span-two"><input autoFocus id="title" name="title" required maxLength="180" placeholder="e.g. Port congestion in East Asia" /></Field>
    <Field label="Event type" name="disruption_type"><select name="disruption_type" defaultValue="logistics"><option value="logistics">Logistics</option><option value="supplier">Supplier</option><option value="weather">Weather</option><option value="geopolitical">Geopolitical</option><option value="quality">Quality</option><option value="other">Other</option></select></Field>
    <Field label="Severity" name="severity"><select name="severity" defaultValue="medium"><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></Field>
    <Field label="Affected region" name="affected_region"><input name="affected_region" maxLength="120" placeholder="e.g. East Asia" /></Field>
    <Field label="Affected supplier" name="affected_supplier"><select name="affected_supplier" defaultValue=""><option value="">No supplier selected</option>{suppliers.map((supplier) => <option value={supplier.id} key={supplier.id}>{supplier.name} · {supplier.code}</option>)}</select></Field>
    <Field label="Evidence confidence" name="confidence" hint="How certain is the reported information?"><div className="input-suffix"><input name="confidence" type="number" min="0" max="100" defaultValue="80" /><span>%</span></div></Field>
    <Field label="Description" name="description" className="span-two"><textarea name="description" rows="3" maxLength="4000" placeholder="What happened, and which routes or operations may be affected?" /></Field>
    {lookupError && <p className="field-hint span-two">Supplier list unavailable: {lookupError}</p>}
  </FormDialog>
}

function MovementForm({ onClose, onSubmit, saving }) {
  const [inventory, setInventory] = useState([])
  const [movementType, setMovementType] = useState('receipt')
  const [lookupError, setLookupError] = useState('')
  useEffect(() => { request('/inventory/').then((payload) => setInventory(rowsFrom(payload))).catch((error) => setLookupError(error.message)) }, [])
  return <FormDialog title="Record stock movement" eyebrow="INVENTORY CONTROL" description="Record a receipt, issue, or adjustment against a warehouse stock balance." onClose={onClose} onSubmit={(event) => {
    const form = new FormData(event.currentTarget)
    const quantity = Math.abs(Number(form.get('quantity')))
    const direction = form.get('adjustment_direction')
    const quantityDelta = movementType === 'issue' || (movementType === 'adjustment' && direction === 'decrease') ? -quantity : quantity
    const payload = {
      inventory: form.get('inventory'),
      movement_type: movementType,
      quantity_delta: quantityDelta.toFixed(2),
      reference: form.get('reference'),
      notes: form.get('notes'),
    }
    return onSubmit(payload)
  }} saving={saving} submitLabel="Post movement">
    <Field label="Inventory balance" name="inventory" className="span-two"><select name="inventory" required defaultValue=""><option value="" disabled>Select a material and location</option>{inventory.map((item) => <option value={item.id} key={item.id}>{item.material_sku} · {item.warehouse_name || item.location} · on hand {formatNumber(item.quantity)}</option>)}</select></Field>
    <Field label="Movement type" name="movement_type"><select name="movement_type" value={movementType} onChange={(event) => setMovementType(event.target.value)}><option value="receipt">Receipt · increase stock</option><option value="issue">Issue · decrease stock</option><option value="adjustment">Adjustment</option></select></Field>
    {movementType === 'adjustment'
      ? <Field label="Adjustment direction" name="adjustment_direction"><select name="adjustment_direction"><option value="increase">Increase</option><option value="decrease">Decrease</option></select></Field>
      : <div className="form-field field-note"><span className="field-label">Stock effect</span><span className={`effect-label ${movementType}`}>{movementType === 'receipt' ? '＋ Adds to on-hand' : '− Removes from on-hand'}</span></div>}
    <Field label="Quantity" name="quantity"><input name="quantity" required type="number" min="0.01" step="0.01" defaultValue="1.00" /></Field>
    <Field label="Reference" name="reference"><input name="reference" maxLength="80" placeholder="Delivery note or ticket" /></Field>
    <Field label="Notes" name="notes" className="span-two"><textarea name="notes" rows="2" maxLength="500" placeholder="Optional context for the movement" /></Field>
    {!inventory.length && !lookupError && <p className="field-hint span-two">Loading inventory balances…</p>}
    {lookupError && <p className="field-hint span-two">Inventory list unavailable: {lookupError}</p>}
  </FormDialog>
}

function PurchaseOrderForm({ onClose, onSubmit, saving }) {
  const [suppliers, setSuppliers] = useState([])
  const [materials, setMaterials] = useState([])
  const [lookupError, setLookupError] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [lines, setLines] = useState([{ material: '', quantity: '1.00', unit_price: '0.00' }])
  useEffect(() => {
    Promise.all([request('/suppliers/'), request('/materials/')])
      .then(([supplierPayload, materialPayload]) => { setSuppliers(rowsFrom(supplierPayload)); setMaterials(rowsFrom(materialPayload)) })
      .catch((error) => setLookupError(error.message))
  }, [])

  function updateLine(index, key, value) {
    setLines((currentLines) => currentLines.map((line, lineIndex) => lineIndex === index ? { ...line, [key]: value } : line))
  }

  const total = lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0)
  return <FormDialog title="Create purchase order" eyebrow="PROCUREMENT" description="Add supplier commitment details and one or more material lines." onClose={onClose} onSubmit={(event) => {
    const form = new FormData(event.currentTarget)
    const payload = {
      number: form.get('number'),
      supplier: form.get('supplier'),
      currency: form.get('currency'),
      lines: lines.map((line, index) => ({ line_number: index + 1, material: line.material, quantity: line.quantity, unit_price: line.unit_price })),
    }
    const expectedDate = form.get('expected_date')
    if (expectedDate) payload.expected_date = expectedDate
    return onSubmit(payload)
  }} saving={saving} submitLabel="Create purchase order">
    <Field label="PO number" name="number"><input autoFocus name="number" required maxLength="40" placeholder="e.g. PO-2026-1044" /></Field>
    <Field label="Supplier" name="supplier"><select name="supplier" required defaultValue=""><option value="" disabled>Select a supplier</option>{suppliers.map((supplier) => <option value={supplier.id} key={supplier.id}>{supplier.name} · {supplier.code}</option>)}</select></Field>
    <Field label="Expected date" name="expected_date"><input name="expected_date" type="date" /></Field>
    <Field label="Currency" name="currency"><select name="currency" value={currency} onChange={(event) => setCurrency(event.target.value)}><option>USD</option><option>EUR</option><option>GBP</option><option>SGD</option></select></Field>
    <div className="line-editor span-two">
      <div className="line-editor-heading"><div><strong>Order lines</strong><small>Select materials and quantities for this commitment.</small></div><button type="button" className="text-button" onClick={() => setLines((currentLines) => [...currentLines, { material: '', quantity: '1.00', unit_price: '0.00' }])}>＋ Add line</button></div>
      {lines.map((line, index) => <div className="po-line" key={index}>
        <span className="po-line-index">{String(index + 1).padStart(2, '0')}</span>
        <select aria-label={`Material for line ${index + 1}`} required value={line.material} onChange={(event) => updateLine(index, 'material', event.target.value)}><option value="" disabled>Select material</option>{materials.map((material) => <option value={material.id} key={material.id}>{material.sku} · {material.name}</option>)}</select>
        <input aria-label={`Quantity for line ${index + 1}`} required type="number" min="0.01" step="0.01" value={line.quantity} onChange={(event) => updateLine(index, 'quantity', event.target.value)} />
        <input aria-label={`Unit price for line ${index + 1}`} required type="number" min="0" step="0.01" value={line.unit_price} onChange={(event) => updateLine(index, 'unit_price', event.target.value)} />
        <button type="button" className="remove-line" aria-label={`Remove line ${index + 1}`} onClick={() => setLines((currentLines) => currentLines.length > 1 ? currentLines.filter((_, lineIndex) => lineIndex !== index) : currentLines)}>×</button>
      </div>)}
      <div className="order-total"><span>Estimated order value</span><strong>{formCurrency(total, currency)}</strong></div>
    </div>
    {lookupError && <p className="field-hint span-two">Supplier or material list unavailable: {lookupError}</p>}
    {(!suppliers.length || !materials.length) && !lookupError && <p className="field-hint span-two">Loading suppliers and materials…</p>}
  </FormDialog>
}

function formCurrency(value, currency = 'USD') {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value || 0)
}

export default App
