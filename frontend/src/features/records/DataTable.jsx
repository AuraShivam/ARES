import { SECTIONS } from '../../config/navigation.js'
import { compactId, formatDate, formatNumber, humanize } from '../../lib/format.js'

export default function DataTable({ section, columns, records, total, search, onSearch, sort, onSort, onExport, onAssess, onManagePlan, busyId }) {
  return <>
    <div className="table-toolbar">
      <label className="search-field"><span aria-hidden="true">⌕</span><input aria-label={`Search ${SECTIONS[section].title}`} placeholder={`Search ${SECTIONS[section].title.toLowerCase()}…`} value={search} onChange={(event) => onSearch(event.target.value)} /></label>
      <div className="table-tools"><span className="row-count">Showing <strong>{records.length}</strong> of {total}</span><button className="secondary-button export-button" onClick={onExport} disabled={!records.length}><span>↓</span> Export CSV</button></div>
    </div>
    {records.length === 0
      ? <div className="table-empty"><span>{search ? '⌕' : '▤'}</span><strong>{search ? 'No matching records' : 'No records yet'}</strong><small>{search ? 'Try a different search term.' : section === 'response-plans' ? 'Create a response plan to assign owners and track disruption work.' : 'Seed the local database to load the ARES demo network.'}</small></div>
      : <div className="table-scroll"><table className="data-table">
        <thead><tr>{columns.map(([key, title]) => <th key={key}>{title ? <button className="sort-button" onClick={() => onSort(key)}>{title}<span>{sort.key === key ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ' ↕'}</span></button> : 'Action'}</th>)}</tr></thead>
        <tbody>{records.map((record) => <tr key={record.id}>{columns.map(([key]) => <td key={key}>
          {key === 'assess'
            ? <button className="assess-button table-assess" onClick={() => onAssess(record.id)} disabled={busyId === record.id}>{busyId === record.id ? 'Scoring…' : 'Assess risk'}</button>
            : key === 'manage_plan'
              ? <button className="assess-button table-assess" onClick={() => onManagePlan(record.id)}>Manage</button>
            : <TableCell section={section} field={key} record={record} />}
        </td>)}</tr>)}</tbody>
      </table></div>}
  </>
}

function TableCell({ section, field, record }) {
  if (field === 'line_count') return <span className="count-cell">{record.lines?.length ?? 0} <small>lines</small></span>
  if (field === 'action_count') return <span className="count-cell">{record.actions?.length ?? 0} <small>actions</small></span>
  if (field === 'changes') return <details className="change-details"><summary>View snapshot</summary><pre>{JSON.stringify(record.changes, null, 2)}</pre></details>
  const value = record[field]
  if (value === null || value === undefined || value === '') return <span className="muted-cell">—</span>
  if (['status', 'severity', 'criticality', 'movement_type', 'action', 'warehouse_type'].includes(field)) return <StatusBadge value={value} />
  if (field === 'active' || field === 'below_reorder_point') return <StatusBadge value={field === 'active' ? (value ? 'active' : 'inactive') : (value ? 'reorder' : 'healthy')} />
  if (['eta', 'expected_date', 'due_date'].includes(field)) return formatDate(value)
  if (field === 'created_at' || field === 'updated_at' || field === 'completed_at') return formatDate(value, true)
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

export function StatusBadge({ value }) {
  const normalized = String(value).toLowerCase().replaceAll(' ', '_')
  return <span className={`status-badge status-${normalized}`}><i />{humanize(value)}</span>
}
