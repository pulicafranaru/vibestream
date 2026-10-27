import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'

/* Notification state for the bell and inbox. Read and announced marks live in localStorage, per profile. */

const REFRESH_MS = 5 * 60 * 1000
const ALERT_REFRESH_MS = 60 * 1000
const LIMIT = 50
// More than this at once is a backlog, not news: the rest wait in the inbox.
const MOST_AT_ONCE = 3

function key(name, profileId) {
  return `vibestream.notifications.${name}.${profileId}`
}

function read(name, profileId) {
  try {
    return localStorage.getItem(key(name, profileId)) || ''
  } catch {
    return ''
  }
}

function write(name, profileId, value) {
  try {
    localStorage.setItem(key(name, profileId), value)
  } catch {
    /* private window */
  }
}

/** 'unsupported', 'insecure' (https only), or the permission: 'default', 'granted' or 'denied'. */
export function browserPermission() {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported'
  if (!window.isSecureContext) return 'insecure'
  return window.Notification.permission
}

/** By calendar day, so it agrees with the inbox's Today. */
export function ago(iso) {
  const midnight = (time) => new Date(time).setHours(0, 0, 0, 0)
  const days = Math.round((midnight(Date.now()) - midnight(iso)) / 86400000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  const weeks = Math.floor(days / 7)
  return weeks === 1 ? '1 week ago' : `${weeks} weeks ago`
}

export function useNotifications(profileId, onChoose) {
  const [items, setItems] = useState([])
  const [seen, setSeen] = useState('')
  const [alerts, setAlertsState] = useState(false)
  const [permission, setPermission] = useState(browserPermission)
  const choose = useRef(onChoose)
  choose.current = onChoose

  const load = useCallback(() => {
    if (!profileId) return
    api.notifications(LIMIT).then((data) => setItems(data.items || [])).catch(() => {})
  }, [profileId])

  useEffect(() => {
    if (!profileId) return undefined
    setSeen(read('seen', profileId))
    setAlertsState(read('browser', profileId) === 'on')
    setItems([])
    load()
    return undefined
  }, [profileId, load])

  const live = alerts && permission === 'granted'
  useEffect(() => {
    if (!profileId) return undefined
    const timer = setInterval(load, live ? ALERT_REFRESH_MS : REFRESH_MS)
    return () => clearInterval(timer)
  }, [profileId, load, live])

  // The first list a profile sees only sets the mark, so old history is not announced.
  useEffect(() => {
    if (!profileId || !items.length) return
    const newest = items[0].at
    const told = read('announced', profileId)
    write('announced', profileId, newest > told ? newest : told)
    if (!told || !live) return
    items
      .filter((item) => item.at > told)
      .slice(0, MOST_AT_ONCE)
      .forEach((item) => {
        try {
          const note = new window.Notification(item.heading, {
            body: item.text,
            icon: item.image || undefined,
            // Tagged per item, so several open tabs replace the note rather than stack it.
            tag: item.id,
          })
          note.onclick = () => {
            window.focus()
            note.close()
            choose.current?.(item)
          }
        } catch {
          /* some browsers only allow them from a service worker */
        }
      })
  }, [items, profileId, live])

  // The newest item, not the clock, marks the place, so nothing arriving later
  // is swallowed by a fast clock.
  const markSeen = useCallback(() => {
    if (!items.length || !profileId) return
    write('seen', profileId, items[0].at)
    setSeen(items[0].at)
  }, [items, profileId])

  /** Asks for permission the first time; resolves to the resulting permission. */
  const setAlerts = useCallback(async (on) => {
    if (!on) {
      write('browser', profileId, 'off')
      setAlertsState(false)
      return browserPermission()
    }
    let now = browserPermission()
    if (now === 'default') {
      try {
        now = await window.Notification.requestPermission()
      } catch {
        now = browserPermission()
      }
    }
    setPermission(now)
    if (now !== 'granted') return now
    write('browser', profileId, 'on')
    setAlertsState(true)
    if (items.length) write('announced', profileId, items[0].at)
    return now
  }, [profileId, items])

  useEffect(() => {
    const check = () => setPermission(browserPermission())
    window.addEventListener('focus', check)
    return () => window.removeEventListener('focus', check)
  }, [])

  const unread = items.filter((item) => item.at > seen).length
  return { items, seen, unread, markSeen, load, alerts: live, wantsAlerts: alerts, permission, setAlerts }
}
