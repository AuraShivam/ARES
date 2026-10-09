import { describeApiError } from './errors.js'

const API = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/$/, '')
let accessToken = ''
let unauthorizedHandler = null

export function setAccessToken(token) {
  accessToken = token || ''
}

export function clearAccessToken() {
  accessToken = ''
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  if (options.body && !isFormData && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (accessToken && !headers.has('Authorization')) headers.set('Authorization', `Token ${accessToken}`)
  let response
  try {
    response = await fetch(`${API}${path}`, { ...options, headers })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Could not reach the ARES API. Start Django and check the API URL.')
  }

  const bodyText = await response.text()
  let payload = null
  if (bodyText) {
    try { payload = JSON.parse(bodyText) } catch { payload = null }
  }
  if (!response.ok) {
    if (response.status === 401 && accessToken) {
      clearAccessToken()
      try { window.sessionStorage.removeItem('ares-api-token') } catch { /* Storage may be unavailable in embedded contexts. */ }
      unauthorizedHandler?.()
    }
    const message = describeApiError(payload)
    const error = new Error(message || `The API returned HTTP ${response.status}.`)
    error.status = response.status
    throw error
  }
  return payload
}
