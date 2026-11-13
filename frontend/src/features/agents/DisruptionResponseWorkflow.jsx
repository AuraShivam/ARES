import { useEffect, useMemo, useState } from 'react'
import { request } from '../../lib/api.js'
import { formatDate, humanize } from '../../lib/format.js'
import { StatusBadge } from '../records/DataTable.jsx'

const EMPTY_DRAFT = { plan_title: '', plan_owner: '', action_title: '', action_owner: '', action_description: '', due_date: '' }

export default function DisruptionResponseWorkflow({ disruptions, assessments, onOpenResponsePlan }) {
  const [runtime, setRuntime] = useState(null)
  const [history, setHistory] = useState([])
  const [selectedDisruption, setSelectedDisruption] = useState('')
  const [assessmentId, setAssessmentId] = useState('')
  const [execution, setExecution] = useState(null)
  const [recommendationIndex, setRecommendationIndex] = useState(0)
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const assessedDisruptions = useMemo(() => {
    const assessedIds = new Set(assessments.map((item) => item.disruption))
    return disruptions.filter((item) => assessedIds.has(item.id))
  }, [assessments, disruptions])
  const selectedAssessments = useMemo(
    () => assessments.filter((item) => item.disruption === selectedDisruption),
    [assessments, selectedDisruption],
  )
  const recommendations = execution?.result?.recommendations || []
  const selectedRecommendation = recommendations[recommendationIndex]
  const existingPlan = execution?.handoff_plans?.find((item) => item.source_recommendation_index === recommendationIndex)

  useEffect(() => {
    let active = true
    Promise.all([request('/ai/status/'), request('/ai/disruption-workflows/')])
      .then(([statusPayload, historyPayload]) => {
        if (!active) return
        setRuntime(statusPayload)
        setHistory(historyPayload.workflows || [])
      })
      .catch((requestError) => { if (active) setError(requestError.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!assessedDisruptions.some((item) => item.id === selectedDisruption)) {
      setSelectedDisruption(assessedDisruptions[0]?.id || '')
    }
  }, [assessedDisruptions, selectedDisruption])

  useEffect(() => {
    if (!selectedAssessments.some((item) => item.id === assessmentId)) {
      setAssessmentId(selectedAssessments[0]?.id || '')
    }
  }, [assessmentId, selectedAssessments])

  useEffect(() => {
    if (!selectedRecommendation) {
      setDraft(EMPTY_DRAFT)
      return
    }
    setDraft({
      plan_title: selectedRecommendation.title,
      plan_owner: '',
      action_title: selectedRecommendation.title,
      action_owner: '',
      action_description: selectedRecommendation.summary,
      due_date: '',
    })
  }, [execution?.id, recommendationIndex])

  function openWorkflow(item) {
    setExecution(item)
    setSelectedDisruption(item.workflow_disruption)
    setAssessmentId(item.workflow_assessment_snapshot)
    setRecommendationIndex(0)
    setError('')
    setNotice('')
  }

  async function runWorkflow(event) {
    event.preventDefault()
    if (!selectedDisruption || !assessmentId || busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const idempotencyKey = `ares-wf-${window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
      const payload = await request('/ai/disruption-workflows/', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ disruption_id: selectedDisruption, assessment_snapshot_id: assessmentId }),
      })
      setExecution(payload.execution)
      setRecommendationIndex(0)
      setHistory((current) => [payload.execution, ...current.filter((item) => item.id !== payload.execution.id)].slice(0, 50))
      setNotice(payload.execution.status === 'succeeded'
        ? 'Analysis complete. Review the evidence and select a recommendation before creating a draft plan.'
        : payload.execution.status === 'running'
          ? 'The workflow is still running. Its status is saved in recent workflows.'
          : 'The workflow did not complete. Review its status and error details below.')
    } catch (requestError) {
      const failedExecution = requestError.payload?.execution
      if (failedExecution) {
        setExecution(failedExecution)
        setHistory((current) => [failedExecution, ...current.filter((item) => item.id !== failedExecution.id)].slice(0, 50))
      }
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  async function createDraft(event) {
    event.preventDefault()
    if (!execution || !selectedRecommendation || busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const payload = await request(`/ai/disruption-workflows/${execution.id}/handoff/`, {
        method: 'POST',
        body: JSON.stringify({ recommendation_index: recommendationIndex, ...draft }),
      })
      const plan = payload.response_plan
      const updatedExecution = {
        ...execution,
        handoff_plans: [plan, ...(execution.handoff_plans || []).filter((item) => item.id !== plan.id)],
      }
      setExecution(updatedExecution)
      setHistory((current) => current.map((item) => item.id === updatedExecution.id ? updatedExecution : item))
      setNotice('A draft response plan was created. It still requires review and approval.')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  return <section className="panel disruption-workflow-panel">
    <div className="panel-heading">
      <div><p className="eyebrow">HUMAN-REVIEWED AI WORKFLOW</p><h2>Disruption response briefing</h2><p>Coordinate read-only specialist analysis, review its evidence, then hand one selected recommendation to a draft response plan.</p></div>
      {runtime?.runtime?.status && <StatusBadge value={runtime.runtime.status} />}
    </div>

    {error && <div className="form-error" role="alert">{error}</div>}
    {notice && <div className="workflow-notice" role="status">{notice}</div>}
    {loading
      ? <div className="risk-empty">Loading agent availability and workflow history…</div>
      : <>
        <div className="workflow-boundary-note">
          {runtime?.runtime?.status === 'configured'
            ? 'The selected disruption context and read-only ARES evidence will be sent to the configured AI provider. Recommendations cannot change or approve operational records.'
            : 'Agent analysis is unavailable until a provider is configured and external processing is explicitly enabled. Existing workflows remain available below.'}
        </div>
        <form className="workflow-start-form" onSubmit={runWorkflow}>
          <label className="form-field"><span className="field-label">Assessed disruption</span>
            <select value={selectedDisruption} onChange={(event) => { setSelectedDisruption(event.target.value); setExecution(null) }} disabled={!assessedDisruptions.length} required>
              <option value="">Select an assessed disruption</option>
              {assessedDisruptions.map((item) => <option value={item.id} key={item.id}>{item.title} · {humanize(item.severity)}</option>)}
            </select>
          </label>
          <label className="form-field"><span className="field-label">Exact risk assessment</span>
            <select value={assessmentId} onChange={(event) => { setAssessmentId(event.target.value); setExecution(null) }} disabled={!selectedAssessments.length} required>
              {selectedAssessments.map((item) => <option value={item.id} key={item.id}>{formatDate(item.created_at, true)} · {humanize(item.trigger)} · score {item.risk_score}</option>)}
            </select>
          </label>
          <button className="primary-button" type="submit" disabled={busy || runtime?.runtime?.status !== 'configured' || !selectedDisruption || !assessmentId}>
            {busy && !execution ? 'Coordinating…' : 'Run response analysis'}
          </button>
        </form>
        {!assessedDisruptions.length && <p className="risk-data-note">Run an ARES risk assessment for a disruption before starting a response workflow.</p>}

        {history.length > 0 && <div className="workflow-history">
          <strong>Recent disruption workflows</strong>
          <div>{history.slice(0, 5).map((item) => <button type="button" className={execution?.id === item.id ? 'workflow-history-item is-selected' : 'workflow-history-item'} key={item.id} onClick={() => openWorkflow(item)}>
            <span>{item.workflow_disruption_title || 'Disruption'} · {formatDate(item.created_at)}</span><StatusBadge value={item.status} />
          </button>)}</div>
        </div>}

        {execution && <div className="workflow-result">
          <div className="workflow-result-heading"><div><strong>{execution.workflow_disruption_title || 'Disruption response workflow'}</strong><small>Assessment score {execution.workflow_assessment_risk_score ?? '—'} · {formatDate(execution.completed_at || execution.started_at, true)}</small></div><StatusBadge value={execution.status} /></div>
          {execution.status !== 'succeeded'
            ? <p className="risk-data-note">{execution.error_message || 'This workflow did not complete successfully.'}</p>
            : <>
              {execution.result?.findings?.length > 0 && <div className="workflow-findings"><strong>Evidence-backed findings</strong>{execution.result.findings.map((finding, index) => <article key={`${finding.code}-${index}`}><StatusBadge value={finding.severity} /><div><strong>{finding.title}</strong><p>{finding.summary}</p></div></article>)}</div>}
              {recommendations.length > 0
                ? <div className="workflow-recommendation">
                  <label className="form-field"><span className="field-label">Recommendation to hand off</span>
                    <select value={recommendationIndex} onChange={(event) => setRecommendationIndex(Number(event.target.value))}>{recommendations.map((item, index) => <option value={index} key={`${item.action}-${index}`}>{index + 1}. {item.title}</option>)}</select>
                  </label>
                  {selectedRecommendation && <>
                    <div className="workflow-recommendation-copy"><p className="eyebrow">{humanize(selectedRecommendation.action)}</p><h3>{selectedRecommendation.title}</h3><p>{selectedRecommendation.summary}</p></div>
                    <div className="workflow-evidence-list"><strong>Verified evidence references</strong><ul>{(selectedRecommendation.evidence_references || []).map((reference, index) => <li key={`${reference.reference_type}-${reference.reference_id}-${index}`}><span>{humanize(reference.reference_type)}</span><code>{reference.reference_id}</code>{reference.source_name && <small>{reference.source_name}</small>}</li>)}</ul></div>
                    {existingPlan
                      ? <div className="workflow-handoff-complete"><StatusBadge value={existingPlan.status} /><span>Draft plan already exists for this recommendation.</span><button type="button" className="secondary-button" onClick={() => onOpenResponsePlan(existingPlan.id)}>Open response plan</button></div>
                      : <form className="workflow-handoff-form" onSubmit={createDraft}>
                        <strong>Prepare an approval draft</strong>
                        <div className="workflow-handoff-fields">
                          <label className="form-field"><span className="field-label">Plan title</span><input required maxLength={180} value={draft.plan_title} onChange={(event) => setDraft((current) => ({ ...current, plan_title: event.target.value }))} /></label>
                          <label className="form-field"><span className="field-label">Plan owner</span><input required maxLength={120} value={draft.plan_owner} onChange={(event) => setDraft((current) => ({ ...current, plan_owner: event.target.value }))} placeholder="Accountable owner" /></label>
                          <label className="form-field"><span className="field-label">Action item</span><input required maxLength={180} value={draft.action_title} onChange={(event) => setDraft((current) => ({ ...current, action_title: event.target.value }))} /></label>
                          <label className="form-field"><span className="field-label">Action owner</span><input required maxLength={120} value={draft.action_owner} onChange={(event) => setDraft((current) => ({ ...current, action_owner: event.target.value }))} placeholder="Person responsible" /></label>
                          <label className="form-field"><span className="field-label">Target date</span><input type="date" value={draft.due_date} onChange={(event) => setDraft((current) => ({ ...current, due_date: event.target.value }))} /></label>
                          <label className="form-field workflow-action-description"><span className="field-label">Action details</span><textarea rows="2" maxLength={5000} value={draft.action_description} onChange={(event) => setDraft((current) => ({ ...current, action_description: event.target.value }))} /></label>
                        </div>
                        <div className="workflow-review-actions"><small>Creates an editable draft only. An approver must review and approve it before work can start.</small><button type="submit" className="primary-button" disabled={busy || !selectedRecommendation.requires_human_approval}>{busy ? 'Creating draft…' : 'Create draft for review'}</button></div>
                      </form>}
                  </>}
                </div>
                : <div className="risk-empty">The coordinator returned no actionable recommendations. Review the findings and uncertainty above.</div>}
              {execution.result?.assumptions?.length > 0 && <details className="workflow-assumptions"><summary>Assumptions and data gaps</summary><ul>{execution.result.assumptions.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>{execution.result.uncertainty && <p>{execution.result.uncertainty}</p>}</details>}
            </>}
        </div>}
      </>}
  </section>
}
