import { useEffect, useMemo, useState } from 'react'
import { request } from '../../lib/api.js'
import { StatusBadge } from '../records/DataTable.jsx'

function csvCell(value) {
  return `"${String(value).replaceAll('"', '""')}"`
}

function downloadTemplate(entity) {
  const csv = entity.columns.map(csvCell).join(',') + '\r\n'
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `ares-${entity.key.replaceAll('_', '-')}-template.csv`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function ImportDialog({ onClose, onCommitted }) {
  const [metadata, setMetadata] = useState(null)
  const [entityType, setEntityType] = useState('')
  const [sourceName, setSourceName] = useState('')
  const [duplicatePolicy, setDuplicatePolicy] = useState('skip')
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [loadingTemplates, setLoadingTemplates] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    request('/imports/templates/')
      .then((payload) => {
        setMetadata(payload)
        setEntityType(payload.entities?.[0]?.key || '')
      })
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoadingTemplates(false))
  }, [])

  const selectedEntity = useMemo(
    () => metadata?.entities?.find((entity) => entity.key === entityType),
    [metadata, entityType],
  )

  function resetPreview() {
    setPreview(null)
    setError('')
  }

  async function handlePreview(event) {
    event.preventDefault()
    setWorking(true)
    setError('')
    setPreview(null)
    try {
      const form = new FormData()
      form.set('entity_type', entityType)
      form.set('source_name', sourceName)
      form.set('duplicate_policy', duplicatePolicy)
      form.set('file', file)
      setPreview(await request('/imports/preview/', { method: 'POST', body: form }))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setWorking(false)
    }
  }

  async function handleCommit() {
    setWorking(true)
    setError('')
    try {
      const committed = await request(`/imports/${preview.id}/commit/`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      await onCommitted(committed)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setWorking(false)
    }
  }

  const hasErrors = Boolean(preview?.error_rows)
  const canCommit = preview && !hasErrors && preview.total_rows > 0

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !working) onClose() }}>
    <section className="dialog import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
      <div className="dialog-header">
        <div><p className="eyebrow">DATA ONBOARDING</p><h2 id="import-title">Import supply-chain CSV</h2><p className="dialog-description">Validate a file and review its effects before writing records to ARES.</p></div>
        <button type="button" className="icon-button" aria-label="Close import dialog" onClick={onClose} disabled={working}>×</button>
      </div>

      <form onSubmit={handlePreview}>
        <div className="import-form-grid">
          <label className="form-field"><span className="field-label">Data type</span>
            <select value={entityType} required disabled={loadingTemplates || working} onChange={(event) => { setEntityType(event.target.value); resetPreview() }}>
              {(metadata?.entities || []).map((entity) => <option value={entity.key} key={entity.key}>{entity.label}</option>)}
            </select>
          </label>
          <label className="form-field"><span className="field-label">Source name</span>
            <input value={sourceName} required maxLength={120} placeholder="e.g. ERP export, supplier workbook" disabled={working} onChange={(event) => { setSourceName(event.target.value); resetPreview() }} />
          </label>
          <label className="form-field"><span className="field-label">When a key already exists</span>
            <select value={duplicatePolicy} disabled={working} onChange={(event) => { setDuplicatePolicy(event.target.value); resetPreview() }}>
              <option value="skip">Skip existing records</option>
              <option value="update">Update included fields</option>
              <option value="error">Flag duplicates as errors</option>
            </select>
          </label>
          <label className="form-field"><span className="field-label">CSV file</span>
            <input type="file" accept=".csv,text/csv" required disabled={working} onChange={(event) => { setFile(event.target.files?.[0] || null); resetPreview() }} />
          </label>
        </div>

        {selectedEntity && <div className="template-row">
          <span>Required columns: <strong>{selectedEntity.required.join(', ')}</strong></span>
          <button type="button" className="secondary-button" onClick={() => downloadTemplate(selectedEntity)}>↓ Download template</button>
        </div>}

        <div className="import-guidance">
          <strong>Safe update behavior</strong>
          <span>Rows match by {selectedEntity?.match_key || 'their natural key'}. Blank optional fields preserve current values during updates. Import suppliers, materials, warehouses, and purchase orders before dependent inventory, shipments, and disruptions. Disruption rows require a stable source key. CSV files must be UTF-8, no larger than 5 MB, with up to {metadata?.limits?.max_rows || 2000} rows.</span>
        </div>

        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="dialog-actions import-actions">
          <button type="button" className="secondary-button" onClick={onClose} disabled={working}>Cancel</button>
          <button type="submit" className="primary-button" disabled={working || loadingTemplates || !metadata}>{working && !preview ? 'Validating…' : 'Validate and preview'}</button>
        </div>
      </form>

      {preview && <section className="import-preview" aria-labelledby="preview-heading">
        <div className="import-preview-heading"><div><p className="eyebrow">PREVIEW · {preview.file_name}</p><h3 id="preview-heading">{preview.total_rows} rows reviewed</h3></div><StatusBadge value={hasErrors ? 'error' : 'preview'} /></div>
        <div className="import-counts">
          {[
            ['Create', preview.created_rows], ['Update', preview.updated_rows],
            ['Skip', preview.skipped_rows], ['Errors', preview.error_rows],
          ].map(([label, count]) => <div className={`import-count ${label.toLowerCase()}`} key={label}><strong>{count}</strong><span>{label}</span></div>)}
        </div>
        <div className="import-row-scroll">
          <table className="import-row-table"><thead><tr><th>CSV row</th><th>Match key</th><th>Action</th><th>Validation</th></tr></thead>
            <tbody>{preview.rows.map((row) => <tr key={row.row_number}>
              <td>{row.row_number}</td><td className="import-key">{row.natural_key || '—'}</td>
              <td><StatusBadge value={row.action} /></td>
              <td>{row.errors?.length ? row.errors.join(' ') : <span className="muted-cell">Ready</span>}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <p className="import-preview-footnote">{hasErrors ? 'Fix the listed rows in the CSV, upload it again, and preview before committing.' : 'The commit rechecks duplicate keys and constraints before saving the whole batch.'}</p>
        <div className="dialog-actions">
          <button type="button" className="secondary-button" onClick={resetPreview} disabled={working}>Start over</button>
          <button type="button" className="primary-button" onClick={handleCommit} disabled={working || !canCommit}>{working ? 'Committing…' : 'Commit import'}</button>
        </div>
      </section>}
    </section>
  </div>
}
