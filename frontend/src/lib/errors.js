import { humanize } from './format.js'

export function describeApiError(value) {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(describeApiError).filter(Boolean).join(' · ')
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([key, detail]) => {
      const message = describeApiError(detail)
      if (!message) return ''
      return key === 'detail' || key === 'non_field_errors' ? message : `${humanize(key)}: ${message}`
    }).filter(Boolean).join(' · ')
  }
  return value == null ? '' : String(value)
}
