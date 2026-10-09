import { formatDate, formatNumber, humanize } from '../../lib/format.js'
import { StatusBadge } from '../records/DataTable.jsx'

export function OverviewPage({ data, homeData, loading, apiHealth, refreshState, lastUpdatedLabel, onNavigate, onAssess, busyId }) {
  const cards = [
    { label: 'Suppliers', value: data?.suppliers, note: 'in the partner network', icon: '♧', tone: 'teal' },
    { label: 'Purchase orders', value: data?.purchase_orders, note: 'orders on record', icon: '▤', tone: 'blue' },
    { label: 'At-risk shipments', value: data?.at_risk_shipments, note: 'delayed or need review', icon: '⇢', tone: 'amber' },
    { label: 'Open disruptions', value: data?.open_disruptions, note: 'awaiting response', icon: '⌁', tone: 'red' },
  ]
  const priorityDisruptions = homeData.disruptions.filter((item) => item.status !== 'resolved').sort((a, b) => severityWeight(b.severity) - severityWeight(a.severity)).slice(0, 4)
  const atRiskShipments = homeData.shipments.filter((shipment) => ['delayed', 'at_risk'].includes(shipment.status)).slice(0, 4)
  const lowInventory = homeData.inventory.filter((balance) => balance.below_reorder_point).slice(0, 4)
  const dataConnected = apiHealth?.status === 'ok' && refreshState !== 'stale'

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
        {homeData.riskAlerts.length > 0 && <div className="overview-alerts" aria-label="Active risk alerts">
          <div className="overview-alerts-heading"><strong>Threshold alerts</strong><span>{homeData.riskAlerts.length} active</span></div>
          {homeData.riskAlerts.slice(0, 3).map((alert) => <div className="mini-row" key={alert.id}>
            <span className={`mini-marker ${['critical', 'high'].includes(alert.risk_band) ? 'is-red' : 'is-amber'}`} />
            <span className="mini-main"><strong>{alert.disruption_title}</strong><small>Alert at score {alert.threshold_score} · {formatDate(alert.last_triggered_at, true)}</small></span>
            <span className="mini-meta"><strong>{alert.risk_score}/100</strong><small>{humanize(alert.risk_band)}</small></span>
          </div>)}
        </div>}
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
          <span className={`connection-icon ${dataConnected ? 'ok' : ''}`}>{dataConnected ? '✓' : '!'}</span>
          <div><strong>Data connection</strong><small>{apiHealth?.database || 'Waiting for API status'} · updated {lastUpdatedLabel}</small></div>
          <span className={`connection-label ${dataConnected ? 'ok' : ''}`}>{refreshState === 'stale' ? 'STALE DATA' : dataConnected ? 'CONNECTED' : 'CONNECTING'}</span>
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

export function LoadingState({ compact = false }) {
  return <div className={`loading-state ${compact ? 'compact' : ''}`} role="status"><span className="spinner" /><span>Loading ARES data…</span></div>
}
