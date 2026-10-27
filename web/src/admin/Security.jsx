import { useEffect, useState } from 'react'
import { admin } from './api'
import { ago, PageHead, Panel, useToast } from './ui'

function browserName(agent) {
  if (!agent) return 'Unknown browser'
  const browser = /Edg\//.test(agent) ? 'Edge' : /Chrome\//.test(agent) ? 'Chrome'
    : /Firefox\//.test(agent) ? 'Firefox' : /Safari\//.test(agent) ? 'Safari' : 'Browser'
  const system = /iPhone|iPad/.test(agent) ? 'iOS' : /Mac OS X/.test(agent) ? 'macOS'
    : /Windows/.test(agent) ? 'Windows' : /Android/.test(agent) ? 'Android' : /Linux/.test(agent) ? 'Linux' : ''
  return system ? `${browser} on ${system}` : browser
}

export default function Security() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sessions, setSessions] = useState(null)
  const say = useToast()

  const load = () => admin.sessions().then((r) => setSessions(r.sessions)).catch(() => {})
  useEffect(() => { load() }, [])

  const change = async (e) => {
    e.preventDefault()
    setError('')
    if (next !== again) {
      setError('The two new passwords are not the same.')
      return
    }
    setBusy(true)
    try {
      await admin.changePassword(current, next)
      setCurrent('')
      setNext('')
      setAgain('')
      say('Password changed. Every other browser is signed out.')
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const end = async (s) => {
    try {
      await admin.endSession(s.id)
      load()
    } catch (err) {
      say(err.message, true)
    }
  }

  return (
    <>
      <PageHead title="Security" text="The admin password, and where it is signed in." />

      <div className="grid two">
        <Panel title="Change the password" icon="lock"
          sub="Changing it signs out every other browser.">
          <form onSubmit={change}>
            <label className="field" style={{ marginBottom: 12 }}>
              <span className="field-label">Current password</span>
              <input className="input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
            </label>
            <label className="field" style={{ marginBottom: 12 }}>
              <span className="field-label">New password</span>
              <input className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
            </label>
            <label className="field" style={{ marginBottom: 12 }}>
              <span className="field-label">Same again</span>
              <input className="input" type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" />
            </label>
            <div className="gate-error">{error}</div>
            <button className="btn primary" disabled={busy || !current || !next || !again}>
              {busy && <span className="spinner" />} Change password
            </button>
          </form>
        </Panel>

        <Panel title="Signed in" icon="globe" sub="A browser stays signed in for 12 hours without use, and 7 days at most.">
          {!sessions && <div className="skeleton" style={{ height: 100 }} />}
          <div className="list">
            {(sessions || []).map((s) => (
              <div className="item" key={s.id}>
                <div className="item-main">
                  <b>{browserName(s.user_agent)} {s.current && <span className="badge ember">This browser</span>}</b>
                  <span>{s.ip}  ·  signed in {ago(s.created_at)}  ·  last seen {ago(s.last_seen_at)}</span>
                </div>
                {!s.current && <button className="btn small danger" onClick={() => end(s)}>Sign out</button>}
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  )
}
