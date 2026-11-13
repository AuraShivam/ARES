import { useEffect, useMemo, useState } from 'react'
import { formatDate, formatNumber, humanize } from '../../lib/format.js'
import { StatusBadge } from '../records/DataTable.jsx'
import DisruptionResponseWorkflow from '../agents/DisruptionResponseWorkflow.jsx'

const RISK_BANDS = ['low', 'moderate', 'high', 'critical']

function MetricCard({ label, value, note, tone = 'teal' }) {
  return <article className="metric-card">
    <div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}>⌁</span></div>
    <strong>{value}</strong>
    <small>{note}</small>
  </article>
}

function DeliveryVerificationForm({ shipments, disruptions, plans, onSubmit, savingId }) {
  const eligible = shipments.filter((item) => item.status === 'delivered' && !item.delivery_outcome_verified)
  const [shipmentId, setShipmentId] = useState('')
  const [actualDate, setActualDate] = useState('')
  const [evidenceNotes, setEvidenceNotes] = useState('')
  const [interventionStatus, setInterventionStatus] = useState('unknown')
  const [responsePlanId, setResponsePlanId] = useState('')

  useEffect(() => {
    if (!eligible.some((item) => item.id === shipmentId)) setShipmentId(eligible[0]?.id || '')
  }, [eligible, shipmentId])

  const selected = eligible.find((item) => item.id === shipmentId)
  useEffect(() => {
    setActualDate(selected?.actual_delivery_date || '')
    setEvidenceNotes('')
    setInterventionStatus('unknown')
    setResponsePlanId('')
  }, [shipmentId, selected?.actual_delivery_date])

  const disruptionIds = disruptions.filter((item) => item.affected_shipment === shipmentId).map((item) => item.id)
  const relatedPlans = plans.filter((plan) => disruptionIds.includes(plan.disruption) && ['active', 'completed'].includes(plan.status))

  async function submit(event) {
    event.preventDefault()
    const saved = await onSubmit(shipmentId, {
      actual_delivery_date: actualDate,
      evidence_notes: evidenceNotes.trim(),
      intervention_status: interventionStatus,
      response_plan_id: interventionStatus === 'ares_plan' ? responsePlanId : null,
    })
    if (saved) {
      setActualDate('')
      setEvidenceNotes('')
    }
  }

  return <section className="panel risk-review-panel">
    <div className="panel-heading"><div><p className="eyebrow">VERIFIED TRAINING DATA</p><h2>Review delivery outcomes</h2><p>Only an approver-verified delivery date can train the delay model.</p></div></div>
    {eligible.length === 0
      ? <div className="risk-empty">No delivered shipments are waiting for outcome verification.</div>
      : <form className="risk-outcome-form" onSubmit={submit}>
        <label className="form-field">
          <span className="field-label">Delivered shipment</span>
          <select value={shipmentId} onChange={(event) => setShipmentId(event.target.value)} required>
            {eligible.map((item) => <option key={item.id} value={item.id}>{item.reference} · {item.purchase_order_number}</option>)}
          </select>
        </label>
        <label className="form-field">
          <span className="field-label">Actual delivery date</span>
          <input type="date" value={actualDate} onChange={(event) => setActualDate(event.target.value)} required />
        </label>
        <label className="form-field risk-evidence-field">
          <span className="field-label">Verification evidence</span>
          <textarea maxLength={10000} rows="3" value={evidenceNotes} onChange={(event) => setEvidenceNotes(event.target.value)} placeholder="Reference the receiving record, carrier proof of delivery, or other verified source." required />
        </label>
        <label className="form-field"><span className="field-label">Intervention before delivery</span>
          <select value={interventionStatus} onChange={(event) => { setInterventionStatus(event.target.value); setResponsePlanId('') }}>
            <option value="unknown">Unknown</option><option value="none">No intervention</option><option value="ares_plan">ARES response plan applied</option><option value="external">External or untracked intervention</option>
          </select>
        </label>
        {interventionStatus === 'ares_plan' && <label className="form-field"><span className="field-label">Applied response plan</span>
          <select required value={responsePlanId} onChange={(event) => setResponsePlanId(event.target.value)}><option value="">Select a linked active/completed plan</option>{relatedPlans.map((plan) => <option value={plan.id} key={plan.id}>{plan.title}</option>)}</select>
        </label>}
        <div className="risk-review-actions">
          <small>Only verified outcomes train or calibrate the delay model. Attribute interventions so mitigated outcomes are not treated as unmitigated predictions.</small>
          <button className="primary-button" type="submit" disabled={savingId === shipmentId || !shipmentId || !actualDate || !evidenceNotes.trim() || (interventionStatus === 'ares_plan' && !responsePlanId)}>{savingId === shipmentId ? 'Saving…' : 'Verify delivery'}</button>
        </div>
      </form>}
  </section>
}

function PredictiveRiskPanel({ report, shipments, disruptions, plans, loading, canReview, onVerifyDelivery, onCapturePrediction, savingId }) {
  const predictions = report?.predictions || []
  const trends = report?.supplier_trends || []
  const [capturedSnapshots, setCapturedSnapshots] = useState({})

  async function capturePrediction(shipmentId) {
    const saved = await onCapturePrediction(shipmentId)
    if (saved) setCapturedSnapshots((current) => ({ ...current, [shipmentId]: saved.id }))
  }
  return <section className="panel predictive-risk-panel">
    <div className="panel-heading">
      <div><p className="eyebrow">PREDICTIVE SUPPLY-CHAIN RISK</p><h2>Shipment delay outlook</h2><p>Trained only from verified historical shipment dates.</p></div>
      {report && <StatusBadge value={report.training_status || 'loading'} />}
    </div>
    {!report && loading
      ? <div className="risk-empty">Preparing the shipment risk model…</div>
      : <>
        <div className="risk-calibration-metrics predictive-model-metrics">
          <span><small>Verified shipments used</small><strong>{formatNumber(report?.verified_shipments_used)}</strong></span>
          <span><small>Late / on time outcomes</small><strong>{formatNumber(report?.late_examples)} / {formatNumber(report?.on_time_examples)}</strong></span>
          <span><small>Model evaluation</small><strong>Experimental</strong></span>
        </div>
        {!report?.predictions_available
          ? <p className="risk-data-note" role="status">{report?.readiness_message || 'Predictive results are not available yet.'} Import historical promised and actual delivery dates, then ask an ARES approver to verify the completed shipment outcomes.</p>
          : predictions.length === 0
            ? <div className="risk-empty">The model is ready, but no planned, in-transit, delayed, or at-risk shipments with an ETA need prediction.</div>
            : <div className="predictive-shipment-list">{predictions.map((item) => <article className="predictive-shipment-card" key={item.shipment_id}>
              <div className="predictive-shipment-heading">
                <div><strong>{item.shipment_reference}</strong><small>{item.purchase_order_number} · {item.supplier_name} · ETA {formatDate(item.eta)}</small></div>
                <span className="predictive-probability">{item.late_probability_percent}%<small> late chance</small></span>
              </div>
              <div className="predictive-shipment-metrics">
                <span><small>Expected delay, if late</small><strong>{item.expected_delay_range_days ? `${item.expected_delay_range_days[0]}–${item.expected_delay_range_days[1]} days` : 'Not enough late examples'}</strong></span>
                <span><small>Model confidence</small><strong>{item.model_confidence_percent}%</strong></span>
                <span><small>Delay-related shortage likelihood</small><strong>{item.material_shortage?.probability_percent == null ? 'Insufficient stock history' : `${item.material_shortage.probability_percent}%`}</strong>{item.material_shortage?.highest_risk_material && <small>{item.material_shortage.highest_risk_material.material_sku} · {item.material_shortage.highest_risk_material.estimated_stock_cover_days} days cover</small>}</span>
              </div>
              {item.factors?.length > 0 && <details className="predictive-factors">
                <summary>Factors influencing this prediction</summary>
                <ul>{item.factors.map((factor) => <li key={`${factor.factor}-${factor.direction}`}><strong>{factor.factor}</strong> {factor.direction} the estimate · {factor.detail}</li>)}</ul>
              </details>}
              {item.material_shortage?.materials?.some((material) => material.estimated_stock_cover_days != null) && <details className="predictive-factors">
                <summary>Material stock-cover detail</summary>
                <ul>{item.material_shortage.materials.map((material) => <li key={material.material_sku}><strong>{material.material_sku}</strong>: {material.estimated_stock_cover_days == null ? material.estimate_note : `${material.estimated_stock_cover_days} days of estimated cover`}{material.baseline_shortage_before_eta ? ' · stock may run out before the promised arrival' : ''}</li>)}</ul>
              </details>}
              <div className="prediction-capture-control">
                <button type="button" className="secondary-button" onClick={() => capturePrediction(item.shipment_id)} disabled={savingId === `prediction:${item.shipment_id}` || Boolean(capturedSnapshots[item.shipment_id])}>
                  {savingId === `prediction:${item.shipment_id}` ? 'Recording…' : capturedSnapshots[item.shipment_id] ? 'Prediction snapshot recorded' : 'Track this prediction'}
                </button>
                {capturedSnapshots[item.shipment_id] && <small>Saved snapshot {capturedSnapshots[item.shipment_id].slice(0, 8)}. Its score will be compared after delivery is verified.</small>}
              </div>
            </article>)}</div>}
        <p className="risk-report-note">{report?.limitations || 'Model probabilities are experimental and require review.'} Confidence is the model’s maximum class probability, not a calibrated guarantee.</p>
        <div className="predictive-lower-grid">
          <section className="predictive-trends">
            <div className="panel-heading"><div><p className="eyebrow">SUPPLIER PERFORMANCE</p><h2>Recent delivery trend</h2><p>Compares verified outcomes from the last 90 days with the prior 90 days.</p></div></div>
            {trends.length === 0
              ? <div className="risk-empty">No verified supplier delivery history yet.</div>
              : <div className="risk-assessment-list">{trends.slice(0, 8).map((item) => <article className="risk-assessment-row" key={item.supplier_code}>
                <div><strong>{item.supplier_name}</strong><small>{item.recent_verified_deliveries} recent / {item.previous_verified_deliveries} prior verified deliveries</small></div>
                <StatusBadge value={item.trend} />
                <span className="risk-alert-score">{item.change_percentage_points == null ? '—' : `${item.change_percentage_points > 0 ? '+' : ''}${item.change_percentage_points} pp`}</span>
              </article>)}</div>}
          </section>
          {canReview
            ? <DeliveryVerificationForm shipments={shipments} disruptions={disruptions} plans={plans} onSubmit={onVerifyDelivery} savingId={savingId} />
            : <section className="panel risk-review-panel"><div className="panel-heading"><div><p className="eyebrow">VERIFIED TRAINING DATA</p><h2>Review delivery outcomes</h2><p>Only ARES approvers can verify delivery outcomes.</p></div></div><div className="risk-data-note">An approver must confirm actual delivery dates and evidence before records enter the model's training set.</div></section>}
        </div>
      </>}
  </section>
}

function OutcomeForm({ disruptions, assessments, outcomes, plans, onSubmit, saving }) {
  const assessedDisruptions = useMemo(() => {
    const ids = new Set(assessments.map((item) => item.disruption))
    return disruptions.filter((item) => ids.has(item.id))
  }, [assessments, disruptions])
  const outcomesByDisruption = useMemo(
    () => new Map(outcomes.map((item) => [item.disruption, item])),
    [outcomes],
  )
  const [disruptionId, setDisruptionId] = useState('')
  const [outcome, setOutcome] = useState('')
  const [evidenceNotes, setEvidenceNotes] = useState('')
  const [assessmentSnapshotId, setAssessmentSnapshotId] = useState('')
  const [interventionStatus, setInterventionStatus] = useState('unknown')
  const [responsePlanId, setResponsePlanId] = useState('')

  useEffect(() => {
    if (!disruptionId && assessedDisruptions.length) setDisruptionId(assessedDisruptions[0].id)
  }, [assessedDisruptions, disruptionId])

  const latestOutcome = outcomesByDisruption.get(disruptionId)
  const selectedAssessments = assessments.filter((item) => item.disruption === disruptionId)
  const relatedPlans = plans.filter((plan) => plan.disruption === disruptionId && ['active', 'completed'].includes(plan.status))
  useEffect(() => {
    setOutcome(latestOutcome?.outcome || '')
    setEvidenceNotes(latestOutcome?.evidence_notes || '')
    setAssessmentSnapshotId(latestOutcome?.assessment_snapshot || selectedAssessments[0]?.id || '')
    setInterventionStatus(latestOutcome?.intervention_status || 'unknown')
    setResponsePlanId(latestOutcome?.response_plan || '')
  }, [disruptionId, latestOutcome?.outcome, latestOutcome?.evidence_notes, latestOutcome?.assessment_snapshot,
    latestOutcome?.intervention_status, latestOutcome?.response_plan, selectedAssessments[0]?.id])

  async function submit(event) {
    event.preventDefault()
    const saved = await onSubmit({
      disruption_id: disruptionId,
      outcome,
      evidence_notes: evidenceNotes.trim(),
      assessment_snapshot_id: assessmentSnapshotId || null,
      intervention_status: interventionStatus,
      response_plan_id: interventionStatus === 'ares_plan' ? responsePlanId : null,
    })
    if (saved) {
      setOutcome('')
      setEvidenceNotes('')
    }
  }

  return <section className="panel risk-review-panel">
    <div className="panel-heading">
      <div><p className="eyebrow">APPROVER REVIEW</p><h2>Record verified outcome</h2><p>Use confirmed supply-chain impact evidence; a GDACS alert alone is not proof.</p></div>
      {latestOutcome && <StatusBadge value="reviewed" />}
    </div>
    {assessedDisruptions.length === 0
      ? <div className="risk-empty">There are no assessed disruptions to review yet.</div>
      : <form className="risk-outcome-form" onSubmit={submit}>
        <label className="form-field">
          <span className="field-label">Assessed disruption</span>
          <select value={disruptionId} onChange={(event) => setDisruptionId(event.target.value)} required>
            {assessedDisruptions.map((item) => {
              const assessment = assessments.find((row) => row.disruption === item.id)
              const label = `${item.title} · ${humanize(item.severity)}${assessment ? ` · score ${assessment.risk_score}` : ''}`
              return <option key={item.id} value={item.id}>{label}</option>
            })}
          </select>
        </label>
        <label className="form-field">
          <span className="field-label">Exact assessment being reviewed</span>
          <select value={assessmentSnapshotId} onChange={(event) => setAssessmentSnapshotId(event.target.value)} required>
            {selectedAssessments.map((item) => <option key={item.id} value={item.id}>{formatDate(item.created_at, true)} · {humanize(item.trigger)} · score {item.risk_score}</option>)}
          </select>
        </label>
        <label className="form-field">
          <span className="field-label">Verified result</span>
          <select value={outcome} onChange={(event) => setOutcome(event.target.value)} required>
            <option value="">Choose a confirmed result</option>
            <option value="impact">Confirmed supply-chain impact</option>
            <option value="no_impact">No material impact</option>
          </select>
        </label>
        <label className="form-field risk-evidence-field">
          <span className="field-label">Evidence notes</span>
          <textarea maxLength={10000} required rows="3" value={evidenceNotes} onChange={(event) => setEvidenceNotes(event.target.value)} placeholder="Describe the confirmed evidence and its source." />
        </label>
        <label className="form-field"><span className="field-label">Intervention attribution</span>
          <select value={interventionStatus} onChange={(event) => { setInterventionStatus(event.target.value); setResponsePlanId('') }}>
            <option value="unknown">Unknown</option><option value="none">No intervention</option><option value="ares_plan">ARES response plan applied</option><option value="external">External or untracked intervention</option>
          </select>
        </label>
        {interventionStatus === 'ares_plan' && <label className="form-field"><span className="field-label">Applied response plan</span>
          <select required value={responsePlanId} onChange={(event) => setResponsePlanId(event.target.value)}><option value="">Select a linked active/completed plan</option>{relatedPlans.map((plan) => <option value={plan.id} key={plan.id}>{plan.title}</option>)}</select>
        </label>}
        {latestOutcome && <p className="risk-correction-note">Last reviewed by {latestOutcome.reviewed_by || 'an ARES approver'} on {formatDate(latestOutcome.reviewed_at, true)}. Saving updates the label and records the correction in audit history.</p>}
        <div className="risk-review-actions">
          <small>Only exact-linked labels marked “No intervention” enter threshold metrics; mitigated or uncertain outcomes remain visible but are excluded.</small>
          <button className="primary-button" type="submit" disabled={saving || !disruptionId || !assessmentSnapshotId || !outcome || !evidenceNotes.trim() || (interventionStatus === 'ares_plan' && !responsePlanId)}>{saving ? 'Saving…' : latestOutcome ? 'Update reviewed outcome' : 'Save reviewed outcome'}</button>
        </div>
      </form>}
  </section>
}

export default function RiskIntelligencePage({ data, loading, canReview, onSubmitOutcome, onVerifyDelivery, onCapturePrediction, onOpenResponsePlan, savingId }) {
  const calibration = data.calibration || {}
  const byBand = calibration.by_risk_band || {}
  const shipmentCalibration = calibration.shipment_prediction_calibration || {}
  const responseEffectiveness = calibration.response_effectiveness || {}
  const activeAlerts = data.alerts.filter((item) => item.status === 'active')
  const assessedDisruptions = new Set(data.assessments.map((item) => item.disruption)).size
  const latestAssessments = data.assessments.slice(0, 8)

  return <div className="risk-intelligence-page">
    <PredictiveRiskPanel report={data.predictive} shipments={data.shipments} disruptions={data.disruptions} plans={data.plans} loading={loading} canReview={canReview} onVerifyDelivery={onVerifyDelivery} onCapturePrediction={onCapturePrediction} savingId={savingId} />
    <DisruptionResponseWorkflow disruptions={data.disruptions} assessments={data.assessments} onOpenResponsePlan={onOpenResponsePlan} />
    <div className="metric-grid">
      <MetricCard label="Alert threshold" value={data.policy?.alert_score_threshold ?? '—'} note="score out of 100" tone="amber" />
      <MetricCard label="Assessed disruptions" value={formatNumber(assessedDisruptions)} note="with saved assessment history" tone="blue" />
      <MetricCard label="Active alerts" value={formatNumber(activeAlerts.length)} note="currently above threshold" tone="red" />
      <MetricCard label="Verified outcomes" value={formatNumber(calibration.labeled_cases)} note={calibration.is_empirically_calibrated ? 'reviewed cases available' : 'needed for empirical calibration'} tone="teal" />
    </div>

    <div className="risk-intelligence-grid">
      <section className="panel risk-calibration-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">RULE EVALUATION</p><h2>Calibration report</h2><p>Latest risk scores compared with approver-reviewed outcomes.</p></div>
          <StatusBadge value={calibration.is_empirically_calibrated ? 'calibrated' : 'not calibrated'} />
        </div>
        <div className="risk-calibration-metrics">
          <span><small>Precision at threshold</small><strong>{calibration.precision_percent == null ? '—' : `${calibration.precision_percent}%`}</strong></span>
          <span><small>Recall at threshold</small><strong>{calibration.recall_percent == null ? '—' : `${calibration.recall_percent}%`}</strong></span>
          <span><small>Labeled with assessment</small><strong>{formatNumber(calibration.assessed_labeled_cases)}</strong></span>
        </div>
        {!data.calibration && loading
          ? <div className="risk-empty">Loading calibration report…</div>
          : calibration.labeled_cases === 0
          ? <p className="risk-data-note" role="status">No verified outcome labels are recorded. ARES cannot estimate predictive performance until approvers review confirmed impact or no-impact evidence.</p>
          : <div className="risk-band-table-wrap"><table className="risk-band-table">
            <thead><tr><th>Risk band</th><th>Reviewed</th><th>Confirmed impact</th><th>Impact rate</th></tr></thead>
            <tbody>{RISK_BANDS.map((band) => {
              const row = byBand[band]
              if (!row) return null
              return <tr key={band}><td><StatusBadge value={band} /></td><td>{formatNumber(row.labeled_cases)}</td><td>{formatNumber(row.confirmed_impact)}</td><td>{row.observed_impact_rate_percent}%</td></tr>
            })}</tbody>
          </table></div>}
        <p className="risk-report-note">Threshold: {formatNumber(calibration.alert_score_threshold)}. This report describes entered labels; it does not train or adjust scoring rules.</p>
      </section>

      <section className="panel risk-alert-panel">
        <div className="panel-heading"><div><p className="eyebrow">THRESHOLD QUEUE</p><h2>Active risk alerts</h2><p>Advisory alerts currently maintained by the risk workflow.</p></div><span className="row-count">{activeAlerts.length} active</span></div>
        {loading && data.alerts.length === 0
          ? <div className="risk-empty">Loading risk alerts…</div>
          : activeAlerts.length === 0
            ? <div className="risk-empty">No active risk alerts.</div>
            : <div className="risk-alert-list">{activeAlerts.map((item) => <article className="risk-alert-row" key={item.id}>
              <div><strong>{item.disruption_title}</strong><small>Triggered {formatDate(item.last_triggered_at, true)}</small></div>
              <StatusBadge value={item.risk_band} />
              <span className="risk-alert-score">{formatNumber(item.risk_score)}<small> / 100</small></span>
            </article>)}</div>}
      </section>
    </div>

    <div className="risk-intelligence-grid risk-learning-grid">
      <section className="panel risk-calibration-panel">
        <div className="panel-heading"><div><p className="eyebrow">SHIPMENT MODEL OUTCOMES</p><h2>Prediction calibration</h2><p>Captured probabilities compared with later approver-verified delivery dates.</p></div></div>
        <div className="risk-calibration-metrics">
          <span><small>Captured predictions</small><strong>{formatNumber(shipmentCalibration.tracked_snapshots)}</strong></span>
          <span><small>Verified outcomes</small><strong>{formatNumber(shipmentCalibration.verified_outcomes)}</strong></span>
          <span><small>No-intervention Brier score</small><strong>{shipmentCalibration.brier_score_no_intervention ?? '—'}</strong></span>
          <span><small>Awaiting verified delivery</small><strong>{formatNumber(shipmentCalibration.pending_outcomes)}</strong></span>
        </div>
        {Object.entries(shipmentCalibration.by_probability_band_no_intervention || {}).some(([, row]) => row.predictions > 0)
          ? <div className="risk-band-table-wrap"><table className="risk-band-table"><thead><tr><th>Predicted band</th><th>Cases</th><th>Mean predicted</th><th>Observed late</th></tr></thead><tbody>{Object.entries(shipmentCalibration.by_probability_band_no_intervention || {}).map(([band, row]) => row.predictions > 0 && <tr key={band}><td>{band}%</td><td>{row.predictions}</td><td>{row.mean_predicted_late_percent}%</td><td>{row.observed_late_percent}%</td></tr>)}</tbody></table></div>
          : <p className="risk-data-note">No tracked shipment predictions have a verified outcome explicitly attributed to no intervention yet.</p>}
        <p className="risk-report-note">Observed results after ARES or external intervention are reported separately: {formatNumber(shipmentCalibration.intervention_breakdown?.ares_plan)} ARES plan · {formatNumber(shipmentCalibration.intervention_breakdown?.external)} external/untracked · {formatNumber(shipmentCalibration.intervention_breakdown?.unknown)} unknown. {shipmentCalibration.limitations}</p>
      </section>

      <section className="panel risk-calibration-panel">
        <div className="panel-heading"><div><p className="eyebrow">APPROVED RESPONSE FOLLOW-UP</p><h2>Action effectiveness</h2><p>Approver-reviewed outcomes linked to the pre-response risk snapshot and completed action evidence.</p></div></div>
        <div className="risk-calibration-metrics">
          <span><small>Completed plans</small><strong>{formatNumber(responseEffectiveness.completed_response_plans)}</strong></span>
          <span><small>Effectiveness reviewed</small><strong>{formatNumber(responseEffectiveness.effectiveness_reviewed_plans)}</strong></span>
          <span><small>Action items completed</small><strong>{formatNumber(responseEffectiveness.action_items_completed)} / {formatNumber(responseEffectiveness.action_items_total)}</strong></span>
          <span><small>Mean linked pre-response risk</small><strong>{responseEffectiveness.mean_pre_response_risk_score ?? '—'}</strong></span>
        </div>
        <div className="risk-effectiveness-list">{Object.entries(responseEffectiveness.latest_review_by_effectiveness || {}).map(([key, value]) => <span key={key}><strong>{formatNumber(value)}</strong>{humanize(key)}</span>)}</div>
        <p className="risk-report-note">Linked verified outcomes: {formatNumber(responseEffectiveness.linked_risk_outcomes?.impact)} impact · {formatNumber(responseEffectiveness.linked_risk_outcomes?.no_impact)} no impact. {responseEffectiveness.limitations}</p>
      </section>
    </div>

    <div className="risk-intelligence-grid risk-lower-grid">
      <section className="panel risk-assessment-panel">
        <div className="panel-heading"><div><p className="eyebrow">ASSESSMENT HISTORY</p><h2>Latest risk assessments</h2><p>Saved scores retain their evidence snapshot and trigger.</p></div></div>
        {loading && data.assessments.length === 0
          ? <div className="risk-empty">Loading assessment history…</div>
          : latestAssessments.length === 0
            ? <div className="risk-empty">No risk assessments have been recorded.</div>
            : <div className="risk-assessment-list">{latestAssessments.map((item) => {
              const disruption = data.disruptions.find((row) => row.id === item.disruption)
              return <article className="risk-assessment-row" key={item.id}>
                <div><strong>{disruption?.title || 'Disruption'}</strong><small>{humanize(item.trigger)} · {formatDate(item.created_at, true)}</small></div>
                <StatusBadge value={item.risk_band} />
                <span className="risk-alert-score">{formatNumber(item.risk_score)}<small> / 100</small></span>
              </article>
            })}</div>}
      </section>

      {canReview
        ? <OutcomeForm disruptions={data.disruptions} assessments={data.assessments} outcomes={data.outcomes} plans={data.plans} onSubmit={onSubmitOutcome} saving={Boolean(savingId)} />
        : <section className="panel risk-review-panel"><div className="panel-heading"><div><p className="eyebrow">APPROVER REVIEW</p><h2>Verified outcomes</h2><p>Outcome labels are restricted to ARES approvers.</p></div></div><div className="risk-data-note">Sign in with an approver account to record or inspect reviewed outcome evidence.</div></section>}
    </div>
  </div>
}
