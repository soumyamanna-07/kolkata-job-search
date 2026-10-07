// Talks to our FastAPI backend. Adds the login token when the user is logged in.
import { supabase } from './supabase'

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

function errorText(data, status) {
  const detail = data && data.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) return detail.map((d) => d.msg.replace(/^Value error, /, '')).join('; ')
  return `Something went wrong (error ${status})`
}

// body = JSON data, form = FormData (file uploads), params = query string
export async function api(path, { method = 'GET', body, form, params } = {}) {
  const url = new URL(API_URL + path)
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  })
  const headers = {}
  const { data: { session } } = await supabase.auth.getSession()
  if (session) headers.Authorization = `Bearer ${session.access_token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(url, { method, headers, body: payload })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your internet, or try again in a minute.')
  }
  if (response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, errorText(data, response.status))
  return data
}

// anonymous id so guest activity (views, apply clicks) can be counted without an account
export function sessionId() {
  let id = null
  try {
    id = localStorage.getItem('kjs_session')
    if (!id) {
      id = crypto.randomUUID().replace(/-/g, '')
      localStorage.setItem('kjs_session', id)
    }
  } catch {
    id = id || 'no-storage'
  }
  return id
}

// record a view / apply click; never blocks or breaks the page
export function trackEvent(jobId, eventType, extra = {}) {
  api('/api/events', {
    method: 'POST',
    body: { job_id: jobId, event_type: eventType, session_id: sessionId(), ...extra },
  }).catch(() => {})
}
