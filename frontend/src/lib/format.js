const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
const STATUS_LABELS = { review: 'Under review', in_transit: 'In transit', at_risk: 'At risk' }
const humanize = (value = '') => STATUS_LABELS[value] || String(value).replaceAll('_', ' ')
const rowsFrom = (payload) => Array.isArray(payload) ? payload : Array.isArray(payload?.results) ? payload.results : []

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? numberFormat.format(number) : String(value)
}

function formatDate(value, includeTime = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, includeTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(date)
}

function formatRelativeTime(value, now = Date.now()) {
  if (!value) return 'Not updated yet'
  const timestamp = value instanceof Date ? value.getTime() : new Date(value).getTime()
  if (!Number.isFinite(timestamp)) return 'Unknown update time'
  const elapsedSeconds = Math.max(0, Math.floor((now - timestamp) / 1000))
  if (elapsedSeconds < 10) return 'just now'
  if (elapsedSeconds < 60) return `${elapsedSeconds}s ago`
  const elapsedMinutes = Math.floor(elapsedSeconds / 60)
  if (elapsedMinutes < 60) return `${elapsedMinutes}m ago`
  const elapsedHours = Math.floor(elapsedMinutes / 60)
  if (elapsedHours < 24) return `${elapsedHours}h ago`
  return `${Math.floor(elapsedHours / 24)}d ago`
}

function compactId(value) {
  return typeof value === 'string' && value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value || '—'
}

export { compactId, formatDate, formatNumber, formatRelativeTime, humanize, rowsFrom }
