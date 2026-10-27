import { useEffect, useState } from 'react'
import { api } from '../api'
import { t, tp } from '../shared/i18n'

// The bell's notifications. Read state is per profile in localStorage: the newest item seen when the list was last opened.

const REFRESH_MS = 5 * 60 * 1000
const LIMIT = 20

let state = { items: [], seen: '', profileId: null }
const listeners = new Set()
let timer = 0

function set(next) {
  state = { ...state, ...next }
  listeners.forEach((listener) => listener(state))
}

const seenKey = (profileId) => `vibestream.notifications.seen.${profileId}`

function readSeen(profileId) {
  try {
    return localStorage.getItem(seenKey(profileId)) || ''
  } catch {
    return ''
  }
}

async function load() {
  const asked = state.profileId
  try {
    const feed = await api.notifications(LIMIT)
    // A profile switched while it was asked for: not this profile's list.
    if (asked === state.profileId) set({ items: (feed && feed.items) || [] })
  } catch {
    /* the bell keeps what it had */
  }
}

export function watchNotes(profileId) {
  clearInterval(timer)
  set({ profileId, items: [], seen: profileId == null ? '' : readSeen(profileId) })
  if (profileId == null) return
  load()
  timer = setInterval(load, REFRESH_MS)
}

export function markNotesRead() {
  const newest = state.items[0] && state.items[0].at
  if (!newest || state.profileId == null) return
  try {
    localStorage.setItem(seenKey(state.profileId), newest)
  } catch {
    /* forgotten next launch */
  }
  set({ seen: newest })
  load()
}

export function useNotes() {
  const [now, setNow] = useState(state)
  useEffect(() => {
    listeners.add(setNow)
    setNow(state)
    return () => listeners.delete(setNow)
  }, [])
  return { items: now.items, unread: now.items.some((item) => item.at > now.seen) }
}

export function ago(iso) {
  const midnight = (time) => new Date(time).setHours(0, 0, 0, 0)
  const days = Math.round((midnight(Date.now()) - midnight(iso)) / 86400000)
  if (days <= 0) return t('Today')
  if (days < 7) return tp('{n} day ago', '{n} days ago', days)
  return tp('{n} week ago', '{n} weeks ago', Math.floor(days / 7))
}
