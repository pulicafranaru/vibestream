import { useEffect, useState } from 'react'
import { NotificationRow } from './Header'

export default function Inbox({ notes, onChoose }) {
  // What was new when the page opened stays marked, though opening it counts as reading it.
  const [since] = useState(notes.seen)
  const [asking, setAsking] = useState(false)

  useEffect(() => {
    notes.load()
  }, [])
  useEffect(() => {
    notes.markSeen()
  }, [notes.items.length])

  const groups = group(notes.items)

  return (
    <div className="page inbox">
      <h1 className="page-title">Notifications</h1>

      <BrowserSwitch notes={notes} asking={asking} setAsking={setAsking} />

      {notes.items.length === 0 && <p className="note">Nothing yet. Finished downloads and new arrivals show up here.</p>}
      {groups.map(([label, items]) => (
        <section key={label} className="inbox-group">
          <h2 className="inbox-heading">{label}</h2>
          <div className="inbox-list">
            {items.map((item) => (
              <NotificationRow
                key={item.id}
                item={item}
                fresh={Boolean(since) && item.at > since}
                onClick={() => onChoose(item)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function BrowserSwitch({ notes, asking, setAsking }) {
  const { permission, wantsAlerts } = notes
  const on = wantsAlerts && permission === 'granted'
  const unavailable = permission === 'unsupported' || permission === 'insecure'
  const blocked = permission === 'denied'

  const flip = async () => {
    setAsking(true)
    try {
      await notes.setAlerts(!on)
    } finally {
      setAsking(false)
    }
  }

  let detail = 'Hear about finished downloads and new arrivals even when this tab is in the background.'
  if (permission === 'insecure') {
    detail = 'Browsers only allow notifications on a secure (https) address. Open VibeStream by its name rather than its LAN address to turn them on.'
  } else if (permission === 'unsupported') {
    detail = "This browser can't show notifications."
  } else if (blocked) {
    detail = "Notifications are blocked for this site. Allow them in the browser's site settings (the icon to the left of the address), then come back."
  }

  return (
    <div className="inbox-switch">
      <div>
        <div className="inbox-switch-title">Browser notifications</div>
        <div className="inbox-switch-detail">{detail}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label="Browser notifications"
        className={`switch ${on ? 'on' : ''}`}
        disabled={asking || unavailable || (blocked && !on)}
        onClick={flip}
      >
        <span className="switch-knob" />
      </button>
    </div>
  )
}

function group(items) {
  const day = 86400000
  const now = Date.now()
  const startOfToday = new Date().setHours(0, 0, 0, 0)
  const buckets = [['Today', []], ['This Week', []], ['Earlier', []]]
  for (const item of items) {
    const at = new Date(item.at).getTime()
    if (at >= startOfToday) buckets[0][1].push(item)
    else if (now - at < 7 * day) buckets[1][1].push(item)
    else buckets[2][1].push(item)
  }
  return buckets.filter(([, list]) => list.length)
}
