/*
 * What is new in the apps since this device last said: once after each
 * update, the server's notes for this app (GET /api/news).
 */
const SEEN = 'vibestream.news.seen'

function read(key) {
  try { return localStorage.getItem(key) } catch { return null }
}

const RETURNING = !!read('vibestream.profile')

export function rememberNews(version) {
  try { localStorage.setItem(SEEN, version) } catch { /* private window */ }
}

/** The releases to tell of, or null when there is nothing new. */
export async function whatsNew(app) {
  const seen = read(SEEN) || (RETURNING ? '1.0.0' : null)
  const query = new URLSearchParams({ app, ...(seen ? { since: seen } : {}) })
  const res = await fetch(`/api/news?${query}`)
  if (!res.ok) return null
  const data = await res.json()
  if (!seen || !data.releases.length) {
    rememberNews(data.version)
    return null
  }
  return data
}
