import { useEffect, useState } from 'react'
import { request } from '../../lib/api.js'
import { formatNumber, rowsFrom } from '../../lib/format.js'
import { StatusBadge } from '../records/DataTable.jsx'

export function AssessmentModal({ result, onClose, onMarkReviewed }) {
  const [reviewing, setReviewing] = useState(false)
  async function markReviewed() {
    setReviewing(true)
    try { await onMarkReviewed(result.disruption_id) } finally { setReviewing(false) }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="dialog assessment-dialog" role="dialog" aria-modal="true" aria-labelledby="assessment-title">
      <div className="dialog-header"><div><p className="eyebrow">ARES RISK ASSESSMENT</p><h2 id="assessment-title">Disruption response brief</h2></div><button className="icon-button" aria-label="Close assessment" onClick={onClose}>×</button></div>
      <div className="risk-summary"><div className="risk-number"><strong>{formatNumber(result.risk_score)}</strong><small>/ 100</small></div><div><StatusBadge value={result.risk_band} /><p>{formatNumber(result.confidence)}% evidence confidence</p></div><span className="model-tag">{result.model || 'Rules v1'}</span></div>
      <h3>Score breakdown</h3>
      {result.score_breakdown?.length
        ? <ul className="score-breakdown">{result.score_breakdown.map((item, index) => <li key={`${item.label}-${index}`}><span><strong>{item.label}</strong><small>{item.detail}</small></span><b>+{item.points}</b></li>)}</ul>
        : <ul className="factor-list">{(result.factors || []).map((factor, index) => <li key={`${factor}-${index}`}>{factor}</li>)}</ul>}
      {result.uncapped_score > result.risk_score && <p className="score-cap-note">Combined evidence totals {result.uncapped_score}; the displayed score is capped at 100.</p>}
      {result.evidence && <section className="evidence-section"><h3>Evidence reviewed</h3>
        <div className="evidence-metrics">
          <span><strong>{result.evidence.open_purchase_orders}</strong><small>Open orders</small></span>
          <span><strong>{result.evidence.delayed_purchase_orders}</strong><small>Delayed orders</small></span>
          <span><strong>{result.evidence.affected_materials}</strong><small>Materials</small></span>
          <span><strong>{result.evidence.materials_below_reorder}</strong><small>Below reorder</small></span>
          <span><strong>{result.evidence.materials_without_inventory}</strong><small>Without stock data</small></span>
          <span><strong>{result.evidence.inventory_coverage_percent === null ? '—' : `${result.evidence.inventory_coverage_percent}%`}</strong><small>Stock coverage</small></span>
          <span><strong>{result.evidence.stale_source_records}</strong><small>Stale sources</small></span>
          <span><strong>{result.evidence.freshness_unknown_records}</strong><small>Unstamped records</small></span>
        </div>
        {result.evidence.regional_matches?.length > 0 && <p className="evidence-detail">Region matched: {result.evidence.regional_matches.join('; ')}</p>}
        {result.evidence.data_gaps?.length > 0 && <div className="evidence-gaps"><strong>Data gaps</strong><ul>{result.evidence.data_gaps.map((gap, index) => <li key={`${gap}-${index}`}>{gap}</li>)}</ul></div>}
      </section>}
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

export function DisruptionForm({ onClose, onSubmit, saving }) {
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

export function MovementForm({ onClose, onSubmit, saving }) {
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

export function PurchaseOrderForm({ onClose, onSubmit, saving }) {
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
