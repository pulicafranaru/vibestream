import { useEffect, useRef, useState } from 'react'
import { Icon } from '../shared/icons'
import { admin } from './api'
import { PageHead, Panel } from './ui'

const LEVELS = [
  { id: '', label: 'Everything' },
  { id: 'error', label: 'Errors' },
  { id: 'warn', label: 'Warnings' },
  { id: 'info', label: 'Info' },
]

export default function Activity() {
  const [events, setEvents] = useState(null)
  const [level, setLevel] = useState('')
  const [source, setSource] = useState('')
  const [sources, setSources] = useState([])

  // Only the newest request may land.
  const seq = useRef(0)
  const load = () => {
    const mine = ++seq.current
    setEvents(null)
    admin.events({ limit: 300, level, source }).then((list) => {
      if (mine !== seq.current) return
      setEvents(list)
      if (!source) setSources([...new Set(list.map((e) => e.source))].sort())
    }).catch(() => mine === seq.current && setEvents([]))
  }
  useEffect(load, [level, source])

  return (
    <>
      <PageHead title="Activity" text="Everything the server has done lately, newest first."
        actions={<button className="btn" onClick={load}><Icon name="replay" size={15} /> Refresh</button>} />

      <Panel>
        <div className="filters" style={{ marginBottom: 14 }}>
          {LEVELS.map((l) => (
            <button key={l.id} className={`chip ${level === l.id ? 'on' : ''}`} onClick={() => setLevel(l.id)}>{l.label}</button>
          ))}
          <select className="input" style={{ width: 180, height: 32, marginLeft: 'auto' }} value={source}
            onChange={(e) => setSource(e.target.value)}>
            <option value="">From anywhere</option>
            {sources.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {!events && <div className="skeleton" style={{ height: 240 }} />}
        {events && events.length === 0 && <div className="empty">Nothing here.</div>}
        <div className="log">
          {(events || []).map((e) => (
            <div key={e.id} className={`log-line ${e.level}`}>
              <time dateTime={e.ts}>{new Date(e.ts).toLocaleString()}</time>
              <span className="source">{e.source}</span>
              <span className="msg">
                {e.message}
                {e.detail && <span className="detail mono">{e.detail.length > 400 ? `${e.detail.slice(0, 400)}...` : e.detail}</span>}
              </span>
            </div>
          ))}
        </div>
      </Panel>
    </>
  )
}
