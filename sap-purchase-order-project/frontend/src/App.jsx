import { useCallback, useEffect, useMemo, useState } from 'react'

const API = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api'
const nav = [
  ['overview', 'Overview', '◫'], ['disruptions', 'Disruptions', '⌁'], ['shipments', 'Shipments', '⇢'],
  ['purchase-orders', 'Purchase orders', '▤'], ['inventory', 'Inventory', '▦'], ['suppliers', 'Suppliers', '♧'], ['materials', 'Materials', '◇'],
]
const fmt = (value) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const label = (value = '') => value.replaceAll('_', ' ')

async function request(path, options) {
  const response = await fetch(`${API}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!response.ok) throw new Error(`API request failed (${response.status})`)
  return response.json()
}

function App() {
  const [section, setSection] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [assessment, setAssessment] = useState(null)
  const [busyId, setBusyId] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const summary = await request('/overview/')
      setOverview(summary)
      if (section !== 'overview') {
        const result = await request(`/${section}/`)
        setRecords(Array.isArray(result) ? result : result.results || [])
      }
    } catch (err) { setError(`${err.message}. Start the Django API and seed demo data to populate ARES.`) }
    finally { setLoading(false) }
  }, [section])

  useEffect(() => { refresh() }, [refresh])
  const currentTitle = nav.find(([key]) => key === section)?.[1] || 'Overview'

  async function assessRisk(disruptionId) {
    setBusyId(disruptionId); setAssessment(null); setError('')
    try { setAssessment(await request('/risk/assess/', { method: 'POST', body: JSON.stringify({ disruption_id: disruptionId }) })) }
    catch (err) { setError(err.message) }
    finally { setBusyId('') }
  }

  async function markReviewed(disruptionId) {
    try {
      await request(`/disruptions/${disruptionId}/`, { method: 'PATCH', body: JSON.stringify({ status: 'review' }) })
      setAssessment(null)
      await refresh()
    } catch (err) { setError(err.message) }
  }

  async function createDemoDisruption() {
    setError('')
    try {
      const suppliers = await request('/suppliers/')
      const supplier = (Array.isArray(suppliers) ? suppliers : suppliers.results || []).find(item => item.status === 'watch')
      const created = await request('/disruptions/', { method: 'POST', body: JSON.stringify({
        title: 'New disruption for review', disruption_type: 'logistics', severity: 'medium',
        affected_region: 'Review required', description: 'Created from ARES dashboard for triage.',
        ...(supplier ? { affected_supplier: supplier.id } : {}),
      }) })
      setSection('disruptions'); setAssessment(await request('/risk/assess/', { method: 'POST', body: JSON.stringify({ disruption_id: created.id }) }))
    } catch (err) { setError(err.message) }
  }

  const cards = useMemo(() => [
    ['Suppliers', overview?.suppliers, 'supplier partners'], ['Purchase orders', overview?.purchase_orders, 'active commitments'],
    ['At risk shipments', overview?.at_risk_shipments, 'need attention'], ['Open disruptions', overview?.open_disruptions, 'awaiting response'],
  ], [overview])

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">A</span><div><strong>ARES</strong><small>RESILIENCE PLATFORM</small></div></div>
      <div className="workspace"><span className="workspace-dot"/> DEMO NETWORK <span className="chevron">⌄</span></div>
      <p className="nav-caption">COMMAND CENTER</p>
      <nav>{nav.map(([key, title, icon]) => <button key={key} onClick={() => { setSection(key); setAssessment(null) }} className={`nav-item ${section === key ? 'selected' : ''}`}><span className="nav-icon">{icon}</span>{title}{key === 'disruptions' && overview?.open_disruptions > 0 && <i>{overview.open_disruptions}</i>}</button>)}</nav>
      <div className="sidebar-bottom"><span className="online-dot"/> Local demo environment <span className="api-tag">API</span><small>HANA connection unverified</small></div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="crumb">ARES <span>/</span> {currentTitle}</div><div className="top-actions"><span className="live"><b/> DEMO DATA</span><button className="icon-button" title="Refresh data" onClick={refresh}>↻</button><div className="avatar">SC</div></div></header>
      <section className="content">
        <div className="page-heading"><div><p className="eyebrow">SUPPLY CHAIN INTELLIGENCE</p><h1>{section === 'overview' ? 'Network overview' : currentTitle}</h1><p className="subtitle">A clear view of operational exposure, emerging risks, and response priorities.</p></div><div className="heading-actions"><span className="date-chip">◷ &nbsp;Live local snapshot</span><button className="primary-button" onClick={createDemoDisruption}>＋ &nbsp;Assess disruption</button></div></div>
        {error && <div className="error-banner"><span>!</span>{error}<button onClick={() => setError('')}>×</button></div>}
        {loading && !overview && <div className="loading">Connecting to the ARES API…</div>}
        {section === 'overview' ? <>
          <div className="stats-grid">{cards.map(([title, value, note], index) => <article className="stat-card" key={title}><div className="stat-top"><span>{title}</span><span className={`stat-icon icon-${index}`}>{['♧', '▤', '⇢', '⌁'][index]}</span></div><strong>{loading && value == null ? '—' : fmt(value)}</strong><small>{note}</small></article>)}</div>
          <div className="overview-grid">
            <section className="panel exposure-panel"><div className="panel-heading"><div><h2>Response queue</h2><p>Disruptions scored for human review</p></div><button className="text-button" onClick={() => setSection('disruptions')}>View all&nbsp; →</button></div><DisruptionList items={null} onAssess={assessRisk} busyId={busyId} loadItems={async () => { const result = await request('/disruptions/'); return Array.isArray(result) ? result : result.results || [] }} /></section>
            <section className="panel health-panel"><div className="panel-heading"><div><h2>Network health</h2><p>Current operating signals</p></div><span className="health-label"><b/> MONITORING</span></div><div className="health-score"><div className="ring"><strong>{overview ? Math.max(0, 100 - (overview.at_risk_shipments || 0) * 11 - (overview.open_disruptions || 0) * 7) : '—'}</strong><small>/ 100</small></div><div><strong>Resilience index</strong><span>Based on current shipment and disruption exposure</span></div></div><div className="health-rows"><HealthRow name="Inventory below reorder" value={overview?.low_inventory || 0} tone="amber"/><HealthRow name="Shipments needing review" value={overview?.at_risk_shipments || 0} tone="red"/><HealthRow name="Open disruption events" value={overview?.open_disruptions || 0} tone="blue"/></div><div className="data-source"><span>i</span><div><strong>Data source</strong><small>Local demo database · SQLite</small></div><span className="source-status">CONNECTED</span></div></section>
          </div>
          <div className="bottom-grid"><section className="panel"><div className="panel-heading"><div><h2>Supply chain flow</h2><p>Master data to operational response</p></div><span className="flow-badge">DIGITAL TWIN</span></div><div className="flow"><FlowNode icon="♧" name="Suppliers" count={overview?.suppliers}/><span className="flow-arrow">→</span><FlowNode icon="◇" name="Materials" count={overview?.materials}/><span className="flow-arrow">→</span><FlowNode icon="▤" name="Orders" count={overview?.purchase_orders}/><span className="flow-arrow">→</span><FlowNode icon="⇢" name="Shipments" count={overview?.at_risk_shipments} alert/></div></section><section className="panel value-panel"><p className="eyebrow">STOCK POSITIONS</p><h2>{overview ? fmt(overview.inventory_records) : '—'}</h2><p>Material and location balances tracked</p><button onClick={() => setSection('inventory')} className="text-button">Explore inventory&nbsp; →</button></section></div>
        </> : <section className="panel table-panel"><div className="panel-heading"><div><h2>{currentTitle}</h2><p>{records.length} records in the local demo dataset</p></div><button className="icon-button" onClick={refresh}>↻</button></div>{section === 'disruptions' ? <DisruptionList items={records} onAssess={assessRisk} busyId={busyId}/> : <DataTable section={section} records={records}/>}</section>}
        {assessment && <Assessment result={assessment} onClose={() => setAssessment(null)} onMarkReviewed={markReviewed}/>}
        <footer><span>ARES · AUTONOMOUS RESILIENT ENTERPRISE SUPPLY CHAIN</span><span>Recommendations support human decision-makers.</span></footer>
      </section>
    </main>
  </div>
}

function HealthRow({ name, value, tone }) { return <div className="health-row"><span><i className={`tone-${tone}`}/>{name}</span><strong>{value}</strong></div> }
function FlowNode({ icon, name, count, alert }) { return <div className={`flow-node ${alert ? 'flow-alert' : ''}`}><span>{icon}</span><strong>{name}</strong><small>{count ?? '—'} records</small></div> }

function DisruptionList({ items, onAssess, busyId, loadItems }) {
  const [data, setData] = useState(items)
  useEffect(() => { setData(items) }, [items])
  useEffect(() => { if (items === null && loadItems) loadItems().then(setData).catch(() => setData([])) }, [])
  if (!data?.length) return <div className="empty-state"><span>⌁</span><strong>No disruptions recorded</strong><small>New events will appear here for review.</small></div>
  return <div className="queue-list">{data.slice(0, 4).map(item => <article className="queue-item" key={item.id}><span className={`severity-dot severity-${item.severity}`}/><div className="queue-main"><strong>{item.title}</strong><span>{item.affected_region || 'Region not specified'} · {item.affected_supplier_name || item.disruption_type}</span></div><span className={`pill pill-${item.severity}`}>{label(item.severity)}</span><button className="assess-button" onClick={() => onAssess(item.id)} disabled={busyId === item.id}>{busyId === item.id ? 'Scoring…' : 'Assess'}</button></article>)}</div>
}

function DataTable({ section, records }) {
  const columns = {
    suppliers: [['code', 'Code'], ['name', 'Supplier'], ['region', 'Region'], ['lead_time_days', 'Lead time'], ['risk_score', 'Risk'], ['status', 'Status']],
    materials: [['sku', 'SKU'], ['name', 'Material'], ['category', 'Category'], ['criticality', 'Criticality'], ['preferred_supplier_name', 'Supplier']],
    inventory: [['material_sku', 'SKU'], ['material_name', 'Material'], ['location', 'Location'], ['quantity', 'On hand'], ['reorder_point', 'Reorder at'], ['below_reorder_point', 'Signal']],
    'purchase-orders': [['number', 'PO number'], ['supplier_name', 'Supplier'], ['material_sku', 'Material'], ['quantity', 'Qty'], ['expected_date', 'Expected'], ['status', 'Status'], ['total_value', 'Value']],
    shipments: [['reference', 'Reference'], ['purchase_order_number', 'PO'], ['origin', 'Origin'], ['destination', 'Destination'], ['eta', 'ETA'], ['risk_score', 'Risk'], ['status', 'Status']],
  }[section] || []
  if (!records.length) return <div className="empty-state"><span>▤</span><strong>No records yet</strong><small>Seed the local database to see the demo network.</small></div>
  return <div className="table-wrap"><table><thead><tr>{columns.map(([, title]) => <th key={title}>{title}</th>)}</tr></thead><tbody>{records.map(record => <tr key={record.id}>{columns.map(([key, title]) => <td key={key}>{key === 'status' || key === 'criticality' || key === 'below_reorder_point' ? <span className={`table-pill ${record[key] === 'blocked' || record[key] === 'delayed' || record[key] === true ? 'table-alert' : ''}`}>{label(String(record[key] ?? '—'))}</span> : record[key] ?? '—'}{key === 'lead_time_days' ? ' days' : ''}</td>)}</tr>)}</tbody></table></div>
}

function Assessment({ result, onClose, onMarkReviewed }) { return <div className="modal-backdrop" onClick={onClose}><section className="assessment-modal" onClick={event => event.stopPropagation()}><div className="modal-heading"><div><p className="eyebrow">ARES RISK ASSESSMENT</p><h2>Disruption response brief</h2></div><button className="icon-button" onClick={onClose}>×</button></div><div className="risk-summary"><div className="risk-number"><strong>{result.risk_score}</strong><small>/100</small></div><div><span className={`pill pill-${result.risk_band}`}>{label(result.risk_band)} exposure</span><p>{result.confidence}% evidence confidence</p></div></div><h3>Why this score</h3><ul className="factor-list">{result.factors.map((factor, index) => <li key={index}>{factor}</li>)}</ul><div className="recommendation"><span>✦</span><div><strong>Suggested response</strong><p>{result.recommendation}</p></div></div><div className="governance-note">{result.governance}</div><div className="modal-actions"><button className="secondary-button" onClick={onClose}>Close brief</button><button className="primary-button" onClick={() => onMarkReviewed(result.disruption_id)}>Mark reviewed</button></div></section></div> }

export default App
