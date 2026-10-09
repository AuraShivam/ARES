import { useEffect, useState } from 'react'
import { request } from '../../lib/api.js'
import { formatDate, humanize, rowsFrom } from '../../lib/format.js'
import { StatusBadge } from '../records/DataTable.jsx'

const emptyAction = () => ({ title: '', description: '', owner: '', due_date: '', action_type: 'manual', execution_payload_text: '{}' })

function PlanEditor({ initialPlan, disruptions, saving, onCancel, onSave }) {
  const [disruption, setDisruption] = useState(initialPlan?.disruption || '')
  const [title, setTitle] = useState(initialPlan?.title || '')
  const [objective, setObjective] = useState(initialPlan?.objective || '')
  const [owner, setOwner] = useState(initialPlan?.owner || '')
  const [dueDate, setDueDate] = useState(initialPlan?.due_date || '')
  const [actions, setActions] = useState(initialPlan?.actions?.map((item) => ({
    title: item.title, description: item.description, owner: item.owner, due_date: item.due_date || '',
    action_type: item.action_type || 'manual', execution_payload_text: JSON.stringify(item.execution_payload || {}, null, 2),
  })) || [emptyAction()])
  const [editorError, setEditorError] = useState('')

  function updateAction(index, field, value) {
    setActions((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item))
  }

  function submit(event) {
    event.preventDefault()
    let normalizedActions
    try {
      normalizedActions = actions.map((item) => {
        const executionPayload = JSON.parse(item.execution_payload_text || '{}')
        if (!executionPayload || typeof executionPayload !== 'object' || Array.isArray(executionPayload)) {
          throw new Error('Webhook payloads must be JSON objects.')
        }
        return {
          title: item.title.trim(), description: item.description.trim(), owner: item.owner.trim(),
          due_date: item.due_date || null, action_type: item.action_type, execution_payload: executionPayload,
        }
      })
    } catch (parseError) {
      setEditorError(parseError instanceof SyntaxError ? 'Action payload must be valid JSON.' : parseError.message)
      return
    }
    setEditorError('')
    const payload = {
      title: title.trim(), objective: objective.trim(), owner: owner.trim(),
      due_date: dueDate || null,
      actions: normalizedActions,
    }
    if (!initialPlan) payload.disruption = disruption
    onSave(payload)
  }

  return <form onSubmit={submit}>
    <div className="response-plan-form-grid">
      {!initialPlan && <label className="form-field"><span className="field-label">Related disruption</span>
        <select required value={disruption} onChange={(event) => setDisruption(event.target.value)}>
          <option value="" disabled>Select a disruption</option>
          {disruptions.map((item) => <option value={item.id} key={item.id}>{item.title} · {humanize(item.severity)}</option>)}
        </select>
      </label>}
      <label className="form-field"><span className="field-label">Plan title</span><input required maxLength={180} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Reroute critical components" /></label>
      <label className="form-field"><span className="field-label">Plan owner</span><input required maxLength={120} value={owner} onChange={(event) => setOwner(event.target.value)} placeholder="Person accountable for the plan" /></label>
      <label className="form-field"><span className="field-label">Target completion</span><input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
      <label className="form-field response-plan-objective"><span className="field-label">Objective</span><textarea rows="2" value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="Describe the intended response and expected result." /></label>
    </div>
    <div className="response-action-editor">
      <div className="line-editor-heading"><div><strong>Owned action items</strong><small>Add at least one task before submitting for approval.</small></div><button type="button" className="text-button" onClick={() => setActions((current) => [...current, emptyAction()])}>＋ Add action</button></div>
      {actions.map((item, index) => <div className="response-action-fields" key={index}>
        <span className="po-line-index">{String(index + 1).padStart(2, '0')}</span>
        <input aria-label={`Action ${index + 1} title`} required maxLength={180} value={item.title} onChange={(event) => updateAction(index, 'title', event.target.value)} placeholder="Action item" />
        <input aria-label={`Action ${index + 1} owner`} required maxLength={120} value={item.owner} onChange={(event) => updateAction(index, 'owner', event.target.value)} placeholder="Owner" />
        <input aria-label={`Action ${index + 1} due date`} type="date" value={item.due_date} onChange={(event) => updateAction(index, 'due_date', event.target.value)} />
        <button type="button" className="remove-line" aria-label={`Remove action ${index + 1}`} disabled={actions.length === 1} onClick={() => setActions((current) => current.filter((_action, actionIndex) => actionIndex !== index))}>×</button>
        <textarea aria-label={`Action ${index + 1} details`} rows="2" value={item.description} onChange={(event) => updateAction(index, 'description', event.target.value)} placeholder="Optional task detail" />
        <select aria-label={`Action ${index + 1} adapter`} value={item.action_type} onChange={(event) => updateAction(index, 'action_type', event.target.value)}>
          <option value="manual">Manual task</option><option value="webhook">Configured webhook</option>
        </select>
        {item.action_type === 'webhook' && <textarea className="execution-payload-editor" aria-label={`Action ${index + 1} webhook payload`} rows="3" value={item.execution_payload_text} onChange={(event) => updateAction(index, 'execution_payload_text', event.target.value)} placeholder="Webhook JSON payload" />}
      </div>)}
    </div>
    {editorError && <div className="form-error" role="alert">{editorError}</div>}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onCancel} disabled={saving}>Cancel</button><button type="submit" className="primary-button" disabled={saving || (!initialPlan && !disruptions.length)}>{saving ? 'Saving…' : initialPlan ? 'Save draft' : 'Create draft'}</button></div>
  </form>
}

export default function ResponsePlanDialog({ planId, currentUser, onClose, onCreated, onChanged }) {
  const [disruptions, setDisruptions] = useState([])
  const [plan, setPlan] = useState(null)
  const [editing, setEditing] = useState(false)
  const [reviewNotes, setReviewNotes] = useState('')
  const [outcome, setOutcome] = useState('')
  const [cancelReason, setCancelReason] = useState('')
  const [actionOutcomes, setActionOutcomes] = useState({})
  const [loading, setLoading] = useState(Boolean(planId))
  const [saving, setSaving] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!planId) {
      request('/disruptions/').then((payload) => setDisruptions(rowsFrom(payload))).catch((requestError) => setError(requestError.message))
      return
    }
    request(`/response-plans/${planId}/`)
      .then((payload) => setPlan(payload))
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false))
  }, [planId])

  async function createPlan(payload) {
    setSaving(true)
    setError('')
    try {
      const created = await request('/response-plans/', { method: 'POST', body: JSON.stringify(payload) })
      await onCreated(created)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }

  async function updatePlan(payload) {
    setSaving(true)
    setError('')
    try {
      const updated = await request(`/response-plans/${plan.id}/`, { method: 'PATCH', body: JSON.stringify(payload) })
      setPlan(updated)
      setEditing(false)
      await onChanged(updated)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }

  async function transition(name, payload = {}) {
    setSaving(true)
    setError('')
    try {
      const updated = await request(`/response-plans/${plan.id}/${name}/`, { method: 'POST', body: JSON.stringify(payload) })
      setPlan(updated)
      setOutcome(updated.outcome || '')
      await onChanged(updated)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }

  async function updateAction(action, status) {
    const result = actionOutcomes[action.id] || action.outcome || ''
    if (status === 'completed' && !result.trim()) {
      setError(`Add an outcome for “${action.title}” before completing it.`)
      return
    }
    setBusyAction(action.id)
    setError('')
    try {
      const updatedAction = await request(`/response-actions/${action.id}/`, {
        method: 'PATCH', body: JSON.stringify({ status, outcome: result }),
      })
      setPlan((current) => ({ ...current, actions: current.actions.map((item) => item.id === updatedAction.id ? updatedAction : item) }))
      await onChanged(plan)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusyAction('')
    }
  }

  async function executeAction(action, dryRun, retryExecution = null) {
    if (!dryRun && !window.confirm(`Send “${action.title}” to the configured ARES webhook now? This requires an approved, active plan.`)) return
    const idempotencyKey = retryExecution?.idempotency_key || window.crypto?.randomUUID?.() || `ares-${action.id}-${Date.now()}`
    setBusyAction(`${action.id}:execute`)
    setError('')
    try {
      const result = await request(`/response-actions/${action.id}/execute/`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ dry_run: dryRun }),
      })
      setPlan((current) => ({
        ...current,
        actions: current.actions.map((item) => item.id === action.id
          ? { ...item, executions: [result.execution, ...(item.executions || []).filter((entry) => entry.id !== result.execution.id)] }
          : item),
      }))
      await onChanged(plan)
    } catch (requestError) {
      try {
        const refreshed = await request(`/response-plans/${plan.id}/`)
        setPlan(refreshed)
      } catch { /* Keep the execution error visible if the plan refresh also fails. */ }
      setError(requestError.message)
    } finally {
      setBusyAction('')
    }
  }

  function actionTransitions(status) {
    return {
      pending: [['in_progress', 'Start'], ['blocked', 'Block'], ['cancelled', 'Cancel task']],
      in_progress: [['blocked', 'Block'], ['completed', 'Complete'], ['cancelled', 'Cancel task']],
      blocked: [['in_progress', 'Resume'], ['completed', 'Complete'], ['cancelled', 'Cancel task']],
    }[status] || []
  }

  const canEdit = plan && ['draft', 'rejected'].includes(plan.status)
  const canCancel = plan && !['completed', 'cancelled'].includes(plan.status)

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving && !busyAction) onClose() }}>
    <section className="dialog response-plan-dialog" role="dialog" aria-modal="true" aria-labelledby="response-plan-title">
      <div className="dialog-header"><div><p className="eyebrow">DISRUPTION RESPONSE</p><h2 id="response-plan-title">{planId ? (plan?.title || 'Manage response plan') : 'Create response plan'}</h2><p className="dialog-description">Plan work, record review decisions, and track the result.</p></div><button type="button" className="icon-button" aria-label="Close response plan" onClick={onClose} disabled={saving || Boolean(busyAction)}>×</button></div>
      {error && <div className="form-error" role="alert">{error}</div>}
      {!planId && !disruptions.length && !error && <p className="response-empty">Report a disruption before creating a response plan.</p>}
      {!planId && <PlanEditor disruptions={disruptions} saving={saving} onCancel={onClose} onSave={createPlan} />}
      {planId && loading && <div className="loading-state compact"><span className="spinner" />Loading response plan…</div>}
      {planId && plan && editing && <PlanEditor initialPlan={plan} disruptions={[]} saving={saving} onCancel={() => setEditing(false)} onSave={updatePlan} />}
      {planId && plan && !editing && <>
        <div className="response-plan-summary">
          <StatusBadge value={plan.status} />
          <span><small>Disruption</small><strong>{plan.disruption_title}</strong></span>
          <span><small>Owner</small><strong>{plan.owner}</strong></span>
          <span><small>Target date</small><strong>{formatDate(plan.due_date)}</strong></span>
        </div>
        {plan.objective && <p className="response-objective">{plan.objective}</p>}
        {plan.reviewed_by && <div className="review-record"><strong>{humanize(plan.status)} by {plan.reviewed_by}</strong><span>{formatDate(plan.reviewed_at, true)}</span>{plan.review_notes && <p>{plan.review_notes}</p>}</div>}

        <div className="response-actions-list"><div className="response-section-heading"><h3>Action items</h3><span>{plan.actions?.length || 0} assigned</span></div>
          {(plan.actions || []).map((item) => <article className="response-task" key={item.id}>
            <div className="response-task-heading"><div><strong>{item.title}</strong><small>{item.owner} · Due {formatDate(item.due_date)}</small></div><StatusBadge value={item.status} /></div>
            {item.description && <p>{item.description}</p>}
            {item.outcome && <p className="response-task-outcome"><strong>Outcome:</strong> {item.outcome}</p>}
            {plan.status === 'active' && actionTransitions(item.status).length > 0 && <div className="response-task-controls">
              {actionTransitions(item.status).some(([nextStatus]) => nextStatus === 'completed') && <input aria-label={`Outcome for ${item.title}`} value={actionOutcomes[item.id] ?? item.outcome ?? ''} onChange={(event) => setActionOutcomes((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="Record result before completing" />}
              {actionTransitions(item.status).map(([nextStatus, label]) => <button type="button" key={nextStatus} className={nextStatus === 'completed' ? 'primary-button' : 'secondary-button'} onClick={() => updateAction(item, nextStatus)} disabled={Boolean(busyAction) || saving}>{busyAction === item.id ? 'Saving…' : label}</button>)}
            </div>}
            {plan.status === 'active' && ['pending', 'in_progress'].includes(item.status) && <div className="response-execution-controls">
              <button type="button" className="secondary-button" onClick={() => executeAction(item, true)} disabled={Boolean(busyAction) || saving}>{busyAction === `${item.id}:execute` ? 'Recording…' : 'Dry-run'}</button>
              {currentUser?.is_approver && item.action_type === 'webhook' && <button type="button" className="primary-button" onClick={() => executeAction(item, false)} disabled={Boolean(busyAction) || saving}>Execute webhook</button>}
              <small>{item.action_type === 'webhook' ? 'Live calls require a configured adapter and explicit approver confirmation.' : 'Manual actions are tracked; dry-run performs no operational change.'}</small>
            </div>}
            {item.executions?.length > 0 && <div className="response-execution-history">
              {item.executions.slice(0, 3).map((execution) => <div className="response-execution-row" key={execution.id}>
                <StatusBadge value={execution.status} /> <span>{humanize(execution.mode)} · {execution.requested_by} · attempt {execution.attempt_count}</span><small>{formatDate(execution.completed_at || execution.started_at, true)}</small>
                {currentUser?.is_approver && plan.status === 'active' && execution.mode === 'live' && ['failed', 'running'].includes(execution.status) && execution.attempt_count < 3 && <button type="button" className="secondary-button" onClick={() => executeAction(item, false, execution)} disabled={Boolean(busyAction) || saving}>{execution.status === 'running' ? 'Check / retry same key' : 'Retry with same key'}</button>}
              </div>)}
            </div>}
          </article>)}
        </div>

        {plan.status === 'pending_approval' && <div className="response-control-card"><strong>Review decision</strong>{currentUser?.is_approver ? <><p className="reviewer-identity">Decision recorded as {currentUser.display_name || currentUser.username}</p><label className="form-field"><span className="field-label">Review notes</span><textarea rows="2" value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} placeholder="Decision context or rejection reason" /></label><div className="response-inline-actions"><button type="button" className="secondary-button" disabled={saving || !reviewNotes.trim()} onClick={() => transition('reject', { review_notes: reviewNotes })}>Reject</button><button type="button" className="primary-button" disabled={saving} onClick={() => transition('approve', { review_notes: reviewNotes })}>Approve</button></div></> : <p className="reviewer-identity">Awaiting review from an ARES approver. You can still view and track this plan.</p>}</div>}
        {plan.status === 'active' && <div className="response-control-card"><strong>Close the response</strong><label className="form-field"><span className="field-label">Outcome</span><textarea rows="2" value={outcome} onChange={(event) => setOutcome(event.target.value)} placeholder="What changed, and was the disruption contained?" /></label><button type="button" className="primary-button" disabled={saving || Boolean(busyAction) || !outcome.trim() || (plan.actions || []).some((item) => !['completed', 'cancelled'].includes(item.status))} onClick={() => transition('complete', { outcome })}>Complete plan</button></div>}
        {plan.outcome && <div className="response-plan-outcome"><strong>{plan.status === 'cancelled' ? 'Cancellation reason' : 'Recorded outcome'}</strong><p>{plan.outcome}</p></div>}
        <div className="dialog-actions response-workflow-actions">
          {canEdit && <button type="button" className="secondary-button" onClick={() => setEditing(true)} disabled={saving}>Edit draft</button>}
          {['draft', 'rejected'].includes(plan.status) && <button type="button" className="primary-button" onClick={() => transition('submit')} disabled={saving}>Submit for approval</button>}
          {plan.status === 'approved' && <button type="button" className="primary-button" onClick={() => transition('start')} disabled={saving}>Start work</button>}
          {canCancel && <button type="button" className="secondary-button cancel-plan-button" onClick={() => transition('cancel', { reason: cancelReason })} disabled={saving}>Cancel plan</button>}
          {canCancel && <input className="cancel-reason-input" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} placeholder="Reason if cancelling" />}
          {!canEdit && !canCancel && <button type="button" className="secondary-button" onClick={onClose}>Close</button>}
        </div>
      </>}
    </section>
  </div>
}
