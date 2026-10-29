/* X-VibeStream-Admin: 1 blocks cross-site requests; the session is an HttpOnly cookie. */

export const SIGNED_OUT = 'vs-admin-signed-out'

export async function call(path, { method = 'GET', body } = {}) {
  const headers = { 'X-VibeStream-Admin': '1' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api/admin${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    /* no body */
  }
  if (!res.ok) {
    const detail = data && data.detail
    const error = new Error(typeof detail === 'string' ? detail : res.statusText || `Error ${res.status}`)
    error.status = res.status
    error.detail = detail
    error.retryAfter = Number(res.headers.get('Retry-After')) || null
    if (res.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event(SIGNED_OUT))
    throw error
  }
  return data
}

export const admin = {
  state: () => call('/auth/state'),
  setUp: (code, password) => call('/auth/setup', { method: 'POST', body: { code, password } }),
  signIn: (password) => call('/auth/login', { method: 'POST', body: { password } }),
  signOut: () => call('/auth/logout', { method: 'POST' }),
  changePassword: (current, next) => call('/auth/password', { method: 'POST', body: { current, new: next } }),
  sessions: () => call('/auth/sessions'),
  endSession: (id) => call(`/auth/sessions/${id}`, { method: 'DELETE' }),

  overview: () => call('/overview'),
  health: () => call('/health'),
  version: () => call('/version'),
  news: () => call('/news'),
  newsSeen: () => call('/news/seen', { method: 'POST' }),
  events: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== ''))
    return call(`/events${q.toString() ? `?${q}` : ''}`)
  },
  sweep: () => call('/sweep', { method: 'POST' }),
  enrich: () => call('/enrich', { method: 'POST' }),
  reap: (dryRun) => call(`/reap?dry_run=${dryRun ? 'true' : 'false'}`, { method: 'POST' }),

  setup: () => call('/setup'),
  checkSetup: (step) => call(`/setup/check/${step}`, { method: 'POST' }),
  finishSetup: () => call('/setup/finish', { method: 'POST' }),

  config: () => call('/config'),
  saveConfig: (changes) => call('/config', { method: 'PUT', body: changes }),
  resetConfig: (key) => call(`/config/${key}`, { method: 'DELETE' }),

  profiles: () => call('/profiles'),
  resetPin: (id) => call(`/profiles/${id}/pin`, { method: 'DELETE' }),
  setPin: (id, pin) => call(`/profiles/${id}/pin`, { method: 'PUT', body: { pin } }),
  makeProfile: (profile) => call('/profiles', { method: 'POST', body: profile }),
  changeProfile: (id, change) => call(`/profiles/${id}`, { method: 'PATCH', body: change }),
  removeProfile: (id) => call(`/profiles/${id}`, { method: 'DELETE' }),
  devices: () => call('/devices'),
  changeDevice: (id, change) => call(`/devices/${encodeURIComponent(id)}`, { method: 'PATCH', body: change }),
  forgetDevice: (id) => call(`/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}
