import { useMemo, useState } from 'react'
import { formatDate, formatNumber } from '../../lib/format.js'
import { StatusBadge } from '../records/DataTable.jsx'

function Metric({ title, value, note, tone = 'teal' }) {
  return <article className="metric-card">
    <div className="metric-top"><span>{title}</span><span className={`metric-icon ${tone}`}>⌁</span></div>
    <strong>{value}</strong>
    <small>{note}</small>
  </article>
}

export default function DemandPlanningPage({ data, loading }) {
  const [horizon, setHorizon] = useState(30)
  const materials = data?.materials || []
  const summary = useMemo(() => ({
    reorder: materials.filter((item) => item.recommended_reorder_quantity > 0).length,
    stockouts: materials.filter((item) => item.days_until_stockout != null).length,
    idle: materials.filter((item) => item.possible_idle_inventory === true).length,
  }), [materials])

  return <div className="demand-planning-page">
    <div className="metric-grid">
      <Metric title="Materials with forecasts" value={formatNumber(data?.materials_with_forecast)} note={`${formatNumber(data?.materials_total)} materials reviewed`} />
      <Metric title="Reorder reviews" value={formatNumber(summary.reorder)} note="Positive suggested quantities" tone="amber" />
      <Metric title="Projected stockouts" value={formatNumber(summary.stockouts)} note="Within the 90-day outlook" tone="red" />
      <Metric title="Possible idle stock" value={formatNumber(summary.idle)} note="No recorded usage in 90 days" tone="blue" />
    </div>

    <section className="panel demand-panel">
      <div className="panel-heading demand-heading">
        <div><p className="eyebrow">DEMAND FORECASTING · INVENTORY PLANNING</p><h2>Material demand outlook</h2><p>Daily issue history drives forecasts; current stock balances alone are not treated as demand history.</p></div>
        <label className="demand-horizon"><span>Forecast window</span><select value={horizon} onChange={(event) => setHorizon(Number(event.target.value))}>
          {[7, 30, 90].map((days) => <option value={days} key={days}>{days} days</option>)}
        </select></label>
      </div>

      {!data && loading
        ? <div className="risk-empty">Building demand outlook…</div>
        : materials.length === 0
          ? <div className="risk-empty">Add materials and inventory balances to begin planning.</div>
          : <div className="demand-material-list">{materials.map((item) => {
            const forecast = item.forecast_units?.[String(horizon)]
            const hasForecast = item.forecast_available && forecast != null
            return <article className="demand-material-card" key={item.material_id}>
              <div className="demand-material-header">
                <div><strong>{item.material_sku} · {item.material_name}</strong><small>{item.preferred_supplier || 'No preferred supplier'} · {item.lead_time_days}-day lead time ({item.lead_time_basis}) · {item.history_coverage_days} history days</small></div>
                <StatusBadge value={item.criticality} />
              </div>
              <div className="demand-metrics-row">
                <span><small>On hand</small><strong>{formatNumber(item.on_hand)} {item.unit}</strong><em>{item.below_reorder_point ? 'At or below reorder point' : `Reorder point ${formatNumber(item.reorder_point)}`}</em></span>
                <span><small>Forecast demand · {horizon} days</small><strong>{hasForecast ? `${formatNumber(forecast)} ${item.unit}` : 'History needed'}</strong><em>{hasForecast ? `${item.consumption_days} consumption days · ${item.model_confidence} data confidence` : item.readiness_message}</em></span>
                <span><small>Projected stockout</small><strong>{item.stockout_date ? formatDate(item.stockout_date) : hasForecast ? 'Not in 90 days' : 'Unavailable'}</strong><em>{item.days_until_stockout == null ? 'Includes dated open purchase orders' : `In ${item.days_until_stockout} days`}</em></span>
                <span><small>Suggested reorder</small><strong>{item.recommended_reorder_quantity == null ? 'Unavailable' : `${formatNumber(item.recommended_reorder_quantity)} ${item.unit}`}</strong><em>{item.safety_stock_units == null ? 'Requires demand history' : `Safety stock ${formatNumber(item.safety_stock_units)} ${item.unit}`}</em></span>
              </div>
              <p className={`demand-recommendation ${item.days_until_stockout != null && item.days_until_stockout <= item.lead_time_days ? 'is-urgent' : ''}`}>{item.recommendation}</p>
              {item.possible_idle_inventory && <p className="demand-idle-note">Possible idle inventory: no issue movements are recorded in the last 90 days. Verify movement history before treating this as obsolete stock.</p>}
              {!item.forecast_available && <p className="risk-data-note" role="status">{item.readiness_message}</p>}
            </article>
          })}</div>}

      <p className="risk-report-note">{data?.method} {data?.limitations}</p>
    </section>
  </div>
}
