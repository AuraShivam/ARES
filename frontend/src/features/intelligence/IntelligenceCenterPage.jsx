import { useEffect, useMemo, useState } from 'react'
import { request } from '../../lib/api.js'
import { formatDate, humanize } from '../../lib/format.js'
import { StatusBadge } from '../records/DataTable.jsx'

const AGENTS = [
  ['risk_intelligence', 'Risk intelligence', 'Summarize saved disruption and deterministic risk evidence.'],
  ['supplier_intelligence', 'Supplier intelligence', 'Review supplier records and verified delivery history.'],
  ['inventory_intelligence', 'Inventory intelligence', 'Review current balances and recorded demand readiness.'],
  ['logistics_intelligence', 'Logistics intelligence', 'Review recorded shipments and linked disruptions.'],
  ['procurement_intelligence', 'Procurement intelligence', 'Review purchase orders, suppliers, materials, and stock.'],
  ['coordinator', 'Coordinator', 'Run selected specialists in sequence and synthesize their verified evidence.'],
]
const SPECIALISTS = AGENTS.filter(([id]) => id !== 'coordinator').map(([id, title]) => [id, title])
const INITIAL_SPECIALISTS = SPECIALISTS.map(([id]) => id)

function displayValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

function displayReference(reference) {
  return `${humanize(reference.reference_type)} · ${reference.reference_id}${reference.source_name ? ` · ${reference.source_name}` : ''}`
}

function ReadinessPanel({ readiness, loading }) {
  const capabilities = Object.entries(readiness?.capabilities || {})
  const entities = Object.entries(readiness?.entities || {})
  return <section className="panel intelligence-readiness-panel">
    <div className="panel-heading"><div><p className="eyebrow">CURRENT DATA READINESS</p><h2>What ARES can support now</h2><p>Coverage is measured from saved ARES records and does not certify external truth.</p></div>{readiness?.generated_at && <small>Updated {formatDate(readiness.generated_at, true)}</small>}</div>
    <div className="intelligence-entity-counts">{entities.map(([name, value]) => <span key={name}><b>{displayValue(value)}</b>{humanize(name)}</span>)}</div>
    <div className="intelligence-capability-grid">
      {capabilities.map(([key, capability]) => <article className="intelligence-capability" key={key}>
        <div><strong>{humanize(key)}</strong><StatusBadge value={capability.status} /></div>
        <small>{humanize(capability.implementation)}</small>
        <div className="intelligence-evidence-points">{Object.entries(capability.evidence || {}).slice(0, 3).map(([metric, value]) => <span key={metric}>{humanize(metric)} · {displayValue(value)}</span>)}</div>
        {capability.limitations?.length > 0 && <details><summary>Limitations</summary><ul>{capability.limitations.slice(0, 3).map((item) => <li key={item}>{item}</li>)}</ul></details>}
      </article>)}
      {!capabilities.length && <div className="risk-empty">{loading ? 'Loading measured readiness…' : 'Readiness data is unavailable.'}</div>}
    </div>
  </section>
}

function EvidenceList({ references = [] }) {
  if (!references.length) return <p className="intelligence-muted">No evidence references were returned.</p>
  return <ul className="intelligence-reference-list">{references.map((reference, index) => <li key={`${reference.reference_type}-${reference.reference_id}-${index}`}>{displayReference(reference)}</li>)}</ul>
}

function ExecutionResult({ execution }) {
  if (!execution) return <div className="intelligence-empty"><strong>Choose a saved run</strong><span>Agent findings, citations, and specialist stages will appear here.</span></div>
  const result = execution.result || {}
  return <section className="intelligence-result">
    <div className="intelligence-result-heading"><div><strong>{humanize(execution.agent_id)} run</strong><small>{formatDate(execution.created_at || execution.started_at, true)} · {execution.duration_ms ?? '—'} ms · {execution.tool_call_count ?? 0} read calls</small></div><StatusBadge value={execution.status} /></div>
    {execution.error_message && <div className="form-error" role="alert">{execution.error_message}</div>}
    {execution.status === 'succeeded' && <>
      {result.findings?.length > 0 && <div className="intelligence-results-block"><strong>Findings</strong>{result.findings.map((finding, index) => <article className="intelligence-finding" key={`${finding.code}-${index}`}><StatusBadge value={finding.severity} /><div><b>{finding.title}</b><p>{finding.summary}</p><EvidenceList references={finding.evidence_references} /></div></article>)}</div>}
      {result.recommendations?.length > 0 && <div className="intelligence-results-block"><strong>Recommendations · human approval required</strong>{result.recommendations.map((recommendation, index) => <article className="intelligence-recommendation" key={`${recommendation.action}-${index}`}><div><span className="eyebrow">{humanize(recommendation.action)}</span><b>{recommendation.title}</b><p>{recommendation.summary}</p></div><EvidenceList references={recommendation.evidence_references} /></article>)}</div>}
      {result.assumptions?.length > 0 && <details className="intelligence-assumptions"><summary>Assumptions and uncertainty</summary><ul>{result.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>{result.uncertainty && <p>{result.uncertainty}</p>}</details>}
      {execution.steps?.length > 0 && <details className="intelligence-steps"><summary>Specialist stages ({execution.steps.length})</summary>{execution.steps.map((step) => <article key={step.id}><div><strong>{humanize(step.agent_id)} · {humanize(step.kind)}</strong><StatusBadge value={step.status} /></div>{step.error_message && <p>{step.error_message}</p>}{step.result?.findings?.slice(0, 3).map((finding, index) => <p key={`${finding.code}-${index}`}>{finding.title}: {finding.summary}</p>)}</article>)}</details>}
      {execution.input_references?.length > 0 && <details className="intelligence-input-evidence"><summary>All verified input references ({execution.input_references.length})</summary><EvidenceList references={execution.input_references} /></details>}
    </>}
  </section>
}

function AgentConsole({ status, history, selected, onSelect, onRun, busy, error, notice }) {
  const [agentId, setAgentId] = useState('coordinator')
  const [question, setQuestion] = useState('Assess the current supply-chain risks in ARES. Summarize the highest-priority evidence-backed findings, data gaps, and practical options for a human to review.')
  const [specialists, setSpecialists] = useState(INITIAL_SPECIALISTS)
  const limits = status?.execution_limits || {}
  const specialistLimit = Math.max(1, Math.min(limits.max_coordinator_specialists || 5, limits.max_coordinator_tool_calls || 12))
  const providerReady = status?.runtime?.status === 'configured'
  const roles = useMemo(() => AGENTS.map(([id, title, description]) => <option value={id} key={id}>{title} · {description}</option>), [])

  useEffect(() => {
    setSpecialists((current) => current.slice(0, specialistLimit))
  }, [specialistLimit])

  function toggleSpecialist(id) {
    setSpecialists((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : current.length < specialistLimit ? [...current, id] : current)
  }

  function submit(event) {
    event.preventDefault()
    onRun({ agentId, question, specialists: agentId === 'coordinator' ? specialists : undefined })
  }

  return <div className="intelligence-agent-layout">
    <section className="panel intelligence-agent-panel">
      <div className="panel-heading"><div><p className="eyebrow">BOUNDED READ-ONLY AGENTS</p><h2>Start an analysis</h2><p>Agents can read through approved ARES tools. They cannot edit records or execute recommendations.</p></div>{status?.runtime?.status && <StatusBadge value={status.runtime.status} />}</div>
      <div className={providerReady ? 'intelligence-provider-note is-ready' : 'intelligence-provider-note'}>
        {providerReady
          ? `External processing is enabled for ${status.runtime.provider} · ${status.runtime.model}. The question and selected ARES evidence will be sent to that provider.`
          : 'The provider is unavailable or disabled. Configure it locally and explicitly enable external processing before running agents. No provider credentials are shown here.'}
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      {notice && <div className="workflow-notice" role="status">{notice}</div>}
      <form className="intelligence-agent-form" onSubmit={submit}>
        <label className="form-field"><span className="field-label">Agent role</span><select value={agentId} onChange={(event) => setAgentId(event.target.value)}>{roles}</select></label>
        {agentId === 'coordinator' && <fieldset className="intelligence-specialists"><legend>Specialists · up to {specialistLimit}</legend>{SPECIALISTS.map(([id, title]) => <label key={id}><input type="checkbox" checked={specialists.includes(id)} onChange={() => toggleSpecialist(id)} disabled={!specialists.includes(id) && specialists.length >= specialistLimit} /><span>{title}</span></label>)}</fieldset>}
        <label className="form-field"><span className="field-label">Question or analysis request</span><textarea required maxLength={1200} rows="4" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about recorded supply-chain evidence and include any relevant ARES record identifiers." /></label>
        <div className="intelligence-form-footer"><small>Up to {limits.max_tool_calls ?? 4} read calls per specialist · {limits.timeout_seconds ?? 30}s timeout · 5 starts per hour</small><button className="primary-button" type="submit" disabled={!providerReady || busy || !question.trim() || (agentId === 'coordinator' && !specialists.length)}>{busy ? 'Running analysis…' : 'Run agent analysis'}</button></div>
      </form>
      <details className="intelligence-tools"><summary>Available read-only tools ({status?.configured_tool_count ?? 0})</summary><p>{status?.tool_access === 'read_only' ? 'Tools never write operational records.' : 'Tool availability could not be confirmed.'}</p><ul>{(status?.supported_agent_roles || []).map((role) => <li key={role}>{humanize(role)}</li>)}</ul></details>
    </section>
    <section className="panel intelligence-history-panel">
      <div className="panel-heading"><div><p className="eyebrow">AUDITABLE RUN HISTORY</p><h2>Recent analyses</h2><p>Only runs requested by this account appear here.</p></div></div>
      {history.length
        ? <div className="intelligence-run-list">{history.slice(0, 12).map((item) => <button type="button" key={item.id} className={selected?.id === item.id ? 'intelligence-run is-selected' : 'intelligence-run'} onClick={() => onSelect(item)}><span><b>{humanize(item.agent_id)}</b><small>{formatDate(item.created_at, true)} · {item.tool_call_count ?? 0} reads</small></span><StatusBadge value={item.status} /></button>)}</div>
        : <div className="intelligence-empty"><strong>No agent analyses yet</strong><span>Runs will be saved with their model, evidence, and stage results.</span></div>}
      <ExecutionResult execution={selected} />
    </section>
  </div>
}

function EvaluationMetrics({ run }) {
  if (!run) return <div className="intelligence-empty"><strong>Select an evaluation run</strong><span>Chronological holdout metrics and baseline comparisons will appear here.</span></div>
  const metrics = run.metrics || {}
  const readiness = metrics.readiness || {}
  if (run.status !== 'completed') return <div className="intelligence-evaluation-result"><div><StatusBadge value={run.status} /><span>{run.error_message || readiness.reason || 'This run did not produce model metrics.'}</span></div><p>{displayValue(readiness.verified_shipments_by_as_of_date ?? readiness.materials_with_eligible_training_history ?? run.sample_count)} eligible holdout examples/materials · fingerprint {run.data_fingerprint?.slice(0, 12) || 'unavailable'}</p></div>

  if (run.model_type === 'shipment_delay') {
    const classification = metrics.classification || {}
    const model = classification.model || {}
    const baselines = classification.baselines || {}
    const duration = metrics.delay_duration || {}
    return <div className="intelligence-evaluation-result">
      <div className="intelligence-evaluation-metrics">{[['Holdout rows', model.sample_count], ['Brier score', model.brier_score], ['Balanced accuracy', model.balanced_accuracy], ['Precision', model.precision], ['Recall', model.recall], ['ROC AUC', model.roc_auc], ['Delay MAE (days)', duration.available ? duration.mae_days : null], ['Brier gain vs prevalence', classification.brier_improvement_percent_vs_training_prevalence == null ? null : `${classification.brier_improvement_percent_vs_training_prevalence}%`]].map(([label, value]) => <span key={label}><small>{label}</small><strong>{displayValue(value)}</strong></span>)}</div>
      <div className="intelligence-baseline-table"><strong>Holdout Brier score · lower is better</strong><span><b>ARES model</b>{displayValue(model.brier_score)}</span><span><b>Training prevalence baseline</b>{displayValue(baselines.training_late_prevalence?.brier_score)}</span><span><b>Supplier history baseline</b>{displayValue(baselines.point_in_time_supplier_rate?.brier_score)}</span></div>
      <p className="intelligence-muted">These diagnostics describe this chronological holdout only. Model probabilities have not been independently calibrated.</p>
    </div>
  }

  return <div className="intelligence-evaluation-result">
    <div className="intelligence-horizon-grid">{['7', '30', '90'].map((horizon) => {
      const result = metrics.horizons?.[horizon]
      if (!result) return <article key={horizon}><strong>{horizon}-day horizon</strong><p>Metrics unavailable for this run.</p></article>
      return <article key={horizon}><strong>{horizon}-day holdout</strong><span>{displayValue(result.model.material_count)} materials</span><span>Model MAE · {displayValue(result.model.mae_units_per_material)} units</span><span>Baseline MAE · {displayValue(result.baseline.mae_units_per_material)} units</span><span>WAPE · {result.model.wape_percent == null ? '—' : `${displayValue(result.model.wape_percent)}%`}</span><span>MAE improvement · {result.mae_improvement_percent_vs_weekly_seasonal_naive == null ? '—' : `${displayValue(result.mae_improvement_percent_vs_weekly_seasonal_naive)}%`}</span></article>
    })}</div>
    <p className="intelligence-muted">Days without a recorded issue count as zero demand. These historical metrics are not a guarantee of future accuracy.</p>
  </div>
}

function ModelEvaluationConsole({ runs, selected, onSelect, onRun, busy, error, notice }) {
  const [model, setModel] = useState('shipment_delay')
  const [asOfDate, setAsOfDate] = useState('')
  const [filter, setFilter] = useState('all')
  const currentDate = new Date()
  const today = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, '0')}-${String(currentDate.getDate()).padStart(2, '0')}`
  const filtered = filter === 'all' ? runs : runs.filter((run) => run.model_type === filter)
  function submit(event) { event.preventDefault(); onRun({ model, asOfDate }) }
  return <div className="intelligence-evaluation-layout">
    <section className="panel intelligence-agent-panel">
      <div className="panel-heading"><div><p className="eyebrow">CHRONOLOGICAL BACKTESTS</p><h2>Evaluate model quality</h2><p>Run an out-of-time comparison against transparent baselines. Evaluation does not change live predictions.</p></div></div>
      {error && <div className="form-error" role="alert">{error}</div>}{notice && <div className="workflow-notice" role="status">{notice}</div>}
      <form className="intelligence-evaluation-form" onSubmit={submit}>
        <label className="form-field"><span className="field-label">Model</span><select value={model} onChange={(event) => setModel(event.target.value)}><option value="shipment_delay">Shipment delay</option><option value="material_demand">Material demand</option></select></label>
        <label className="form-field"><span className="field-label">As-of date · optional</span><input type="date" max={today} value={asOfDate} onChange={(event) => setAsOfDate(event.target.value)} /></label>
        <button className="primary-button" type="submit" disabled={busy}>{busy ? 'Evaluating…' : 'Run evaluation'}</button>
      </form>
      <p className="intelligence-muted">The API permits two evaluation starts per user per hour. Insufficient history is reported and saved as a run, not treated as a successful benchmark.</p>
      {selected && <EvaluationMetrics run={selected} />}
    </section>
    <section className="panel intelligence-history-panel">
      <div className="panel-heading"><div><p className="eyebrow">SAVED BENCHMARKS</p><h2>Evaluation history</h2><p>Run dates, holdouts, and fingerprints support reproducible review.</p></div></div>
      <label className="intelligence-history-filter"><span className="field-label">Filter runs</span><select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All models</option><option value="shipment_delay">Shipment delay</option><option value="material_demand">Material demand</option></select></label>
      {filtered.length
        ? <div className="intelligence-run-list">{filtered.slice(0, 20).map((run) => <button type="button" className={selected?.id === run.id ? 'intelligence-run is-selected' : 'intelligence-run'} key={run.id} onClick={() => onSelect(run)}><span><b>{humanize(run.model_type)}</b><small>{formatDate(run.created_at, true)} · {run.sample_count} samples · {run.holdout_start_date || 'no holdout'}</small></span><StatusBadge value={run.status} /></button>)}</div>
        : <div className="intelligence-empty"><strong>No evaluation runs</strong><span>Choose a model to create the first persisted benchmark.</span></div>}
    </section>
  </div>
}

export default function IntelligenceCenterPage() {
  const [activeTab, setActiveTab] = useState('agents')
  const [providerStatus, setProviderStatus] = useState(null)
  const [readiness, setReadiness] = useState(null)
  const [history, setHistory] = useState([])
  const [selectedExecution, setSelectedExecution] = useState(null)
  const [evaluations, setEvaluations] = useState([])
  const [selectedEvaluation, setSelectedEvaluation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [agentBusy, setAgentBusy] = useState(false)
  const [evaluationBusy, setEvaluationBusy] = useState(false)
  const [agentError, setAgentError] = useState('')
  const [evaluationError, setEvaluationError] = useState('')
  const [agentNotice, setAgentNotice] = useState('')
  const [evaluationNotice, setEvaluationNotice] = useState('')

  async function load() {
    setRefreshing(true)
    const results = await Promise.allSettled([
      request('/ai/status/'), request('/ai/data-readiness/'), request('/ai/executions/'), request('/models/evaluations/'),
    ])
    const messages = []
    if (results[0].status === 'fulfilled') setProviderStatus(results[0].value)
    else messages.push(`Agent status: ${results[0].reason.message}`)
    if (results[1].status === 'fulfilled') setReadiness(results[1].value)
    else messages.push(`Readiness: ${results[1].reason.message}`)
    if (results[2].status === 'fulfilled') {
      const items = results[2].value.executions || []
      setHistory(items)
      setSelectedExecution((current) => current ? items.find((item) => item.id === current.id) || current : items[0] || null)
    } else messages.push(`Agent history: ${results[2].reason.message}`)
    if (results[3].status === 'fulfilled') {
      const items = results[3].value.results || []
      setEvaluations(items)
      setSelectedEvaluation((current) => current ? items.find((item) => item.id === current.id) || current : items[0] || null)
    } else messages.push(`Model evaluations: ${results[3].reason.message}`)
    setLoadError(messages.join(' · '))
    setLoading(false)
    setRefreshing(false)
  }

  useEffect(() => { load() }, [])

  async function runAgent({ agentId, question, specialists }) {
    setAgentBusy(true); setAgentError(''); setAgentNotice('')
    try {
      const headers = { 'Idempotency-Key': `ares-center-${window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}` }
      const body = { agent_id: agentId, question }
      if (specialists) body.specialists = specialists
      const response = await request('/ai/executions/', { method: 'POST', headers, body: JSON.stringify(body) })
      const execution = response.execution
      setSelectedExecution(execution)
      setHistory((current) => [execution, ...current.filter((item) => item.id !== execution.id)].slice(0, 50))
      setAgentNotice(execution.status === 'succeeded' ? 'Analysis finished. Review its evidence and assumptions before acting.' : `Run status: ${humanize(execution.status)}.`)
    } catch (error) {
      const failed = error.payload?.execution
      if (failed) {
        setSelectedExecution(failed)
        setHistory((current) => [failed, ...current.filter((item) => item.id !== failed.id)].slice(0, 50))
      }
      setAgentError(error.message)
    } finally { setAgentBusy(false) }
  }

  async function runEvaluation({ model, asOfDate }) {
    setEvaluationBusy(true); setEvaluationError(''); setEvaluationNotice('')
    try {
      const body = { model }
      if (asOfDate) body.as_of_date = asOfDate
      const run = await request('/models/evaluations/', { method: 'POST', body: JSON.stringify(body) })
      setSelectedEvaluation(run)
      setEvaluations((current) => [run, ...current.filter((item) => item.id !== run.id)].slice(0, 50))
      setEvaluationNotice(run.status === 'completed' ? 'Evaluation saved. Compare the model against its baselines and review the holdout dates.' : `Evaluation saved with status: ${humanize(run.status)}.`)
    } catch (error) { setEvaluationError(error.message) }
    finally { setEvaluationBusy(false) }
  }

  return <div className="intelligence-center-page">
    <div className="intelligence-center-toolbar"><div><p className="eyebrow">PHASE 9 · AGENTIC AND PREDICTIVE INTELLIGENCE</p><h2>Intelligence workspace</h2><p>Inspect data readiness, run advisory agents, and evaluate forecasts against chronological holdouts.</p></div><button className="secondary-button" type="button" onClick={load} disabled={refreshing}>{refreshing ? 'Refreshing…' : 'Refresh data'}</button></div>
    {loadError && <div className="form-error" role="alert">{loadError}</div>}
    <ReadinessPanel readiness={readiness} loading={loading} />
    <div className="intelligence-tabs" role="tablist" aria-label="Intelligence workspace sections">
      <button type="button" role="tab" aria-selected={activeTab === 'agents'} className={activeTab === 'agents' ? 'is-selected' : ''} onClick={() => setActiveTab('agents')}>Agent control center</button>
      <button type="button" role="tab" aria-selected={activeTab === 'evaluation'} className={activeTab === 'evaluation' ? 'is-selected' : ''} onClick={() => setActiveTab('evaluation')}>Model evaluation</button>
    </div>
    {loading && <div className="risk-empty">Loading agent availability, data coverage, and saved evaluations…</div>}
    {activeTab === 'agents'
      ? <AgentConsole status={providerStatus} history={history} selected={selectedExecution} onSelect={setSelectedExecution} onRun={runAgent} busy={agentBusy} error={agentError} notice={agentNotice} />
      : <ModelEvaluationConsole runs={evaluations} selected={selectedEvaluation} onSelect={setSelectedEvaluation} onRun={runEvaluation} busy={evaluationBusy} error={evaluationError} notice={evaluationNotice} />}
    <p className="intelligence-governance-note">All agents are advisory and read-only. Model evaluations do not change production predictions. Recovery scenarios remain isolated from operational records; review them in the Supply Chain Twin.</p>
  </div>
}
