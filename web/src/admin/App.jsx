import { useCallback, useEffect, useState } from 'react'
import { Icon } from '../shared/icons'
import { VMark, Wordmark } from '../shared/brand'
import { admin, SIGNED_OUT } from './api'
import { ConfigProvider, SaveBar, ToastProvider } from './ui'
import Overview from './Overview'
import Sources from './Sources'
import Library from './Library'
import Playback from './Playback'
import People from './People'
import Activity from './Activity'
import Security from './Security'
import Setup from './Setup'

// A server with no admin asks for the setup code from the server log
// (services/adminauth.py), so reaching the address is not enough to claim it.

const PAGES = [
  { group: 'Server' },
  { id: 'overview', label: 'Overview', icon: 'home', Page: Overview },
  { id: 'activity', label: 'Activity', icon: 'activity', Page: Activity },
  { group: 'Setup' },
  { id: 'sources', label: 'Sources', icon: 'download', Page: Sources },
  { id: 'library', label: 'Library & storage', icon: 'storage', Page: Library },
  { id: 'playback', label: 'Playback', icon: 'now-playing', Page: Playback },
  { group: 'Household' },
  { id: 'people', label: 'People & devices', icon: 'user', Page: People },
  { group: 'Account' },
  { id: 'security', label: 'Security', icon: 'lock', Page: Security },
]

const pageFromPath = () => {
  const id = window.location.pathname.replace(/^\/admin\/?/, '').split('/')[0]
  return PAGES.some((p) => p.id === id) ? id : 'overview'
}

export default function App() {
  const [state, setState] = useState(null)
  const [setupDone, setSetupDone] = useState(null)

  const check = useCallback(() => {
    admin.state().then(setState).catch(() => setState({ configured: true, signed_in: false, offline: true }))
  }, [])

  useEffect(() => {
    if (!state || !state.signed_in) return
    admin.setup().then((s) => setSetupDone(s.done)).catch(() => setSetupDone(true))
  }, [state])

  useEffect(() => { check() }, [check])
  useEffect(() => {
    const out = () => setState((s) => (s ? { ...s, signed_in: false, expired: true } : s))
    window.addEventListener(SIGNED_OUT, out)
    return () => window.removeEventListener(SIGNED_OUT, out)
  }, [])

  if (!state) return null
  if (!state.signed_in) return <Gate state={state} onIn={check} />
  if (setupDone === null) return null
  if (!setupDone) return <Setup onDone={() => setSetupDone(true)} />
  return (
    <ToastProvider>
      <ConfigProvider>
        <Shell onOut={() => setState({ ...state, signed_in: false })} />
      </ConfigProvider>
    </ToastProvider>
  )
}

function Wall() {
  const [posters, setPosters] = useState([])
  useEffect(() => {
    fetch('/api/catalog/home')
      .then((r) => r.json())
      .then((data) => {
        const seen = new Set()
        const all = []
        ;(data.rows || []).forEach((row) => (row.items || []).forEach((item) => {
          if (item.poster && !seen.has(item.poster)) {
            seen.add(item.poster)
            all.push(item.poster)
          }
        }))
        setPosters(all.slice(0, 72))
      })
      .catch(() => {})
  }, [])
  if (!posters.length) return null
  const tiles = [...posters, ...posters].slice(0, 108)
  return (
    <div className="gate-wall" aria-hidden="true">
      {tiles.map((src, i) => <img key={i} src={src} alt="" loading="lazy" />)}
    </div>
  )
}

const COMMAND = 'docker logs vibestream-api 2>&1 | grep "setup code"'

// The clipboard API needs a secure context; over plain http this falls back
// to a hidden textarea and execCommand.
function CopyButton({ text }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const box = document.createElement('textarea')
      box.value = text
      box.style.position = 'fixed'
      box.style.opacity = '0'
      document.body.appendChild(box)
      box.select()
      document.execCommand('copy')
      box.remove()
    }
    setDone(true)
    setTimeout(() => setDone(false), 1600)
  }
  return (
    <button type="button" className={`btn small ${done ? 'done' : ''}`} onClick={copy}
      aria-label={done ? 'Copied' : 'Copy'} title={done ? 'Copied' : 'Copy'}>
      {done ? <Icon name="check" size={15} /> : <CopyGlyph />}
    </button>
  )
}

function CopyGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2.5" />
      <path d="M15 9V6.5A2.5 2.5 0 0 0 12.5 4h-6A2.5 2.5 0 0 0 4 6.5v6A2.5 2.5 0 0 0 6.5 15H9" />
    </svg>
  )
}

function Gate({ state, onIn }) {
  const first = !state.configured
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(state.expired ? 'Signed out. Sign in again to carry on.' : '')

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    if (first && password !== again) {
      setError('The two passwords are not the same.')
      return
    }
    setBusy(true)
    try {
      if (first) await admin.setUp(code, password)
      else await admin.signIn(password)
      onIn()
    } catch (err) {
      setError(err.retryAfter ? `${err.message} (${err.retryAfter}s)` : err.message)
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <Wall />
      <div className="gate-card">
        <span className="gate-mark"><VMark size={64} /></span>
        <h1>{first ? 'Set up the admin' : 'Admin'}</h1>
        <p className="lead">
          {first ? 'Choose the password that runs this server.' : 'Sign in to run this server.'}
        </p>
        <form onSubmit={submit}>
          {first && (
            <>
              <div className="gate-hint">
                The installer showed the setup code when it finished. To see it again, run this on the server:
                <div className="gate-command">
                  <code className="mono">{COMMAND}</code>
                  <CopyButton text={COMMAND} />
                </div>
              </div>
              <label className="field">
                <span className="field-label">Setup code</span>
                <input className="input mono" value={code} onChange={(e) => setCode(e.target.value)}
                  placeholder="XXXX-XXXX" autoComplete="off" autoFocus spellCheck={false} />
              </label>
            </>
          )}
          <label className="field">
            <span className="field-label">{first ? 'New password' : 'Password'}</span>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={first ? 'new-password' : 'current-password'} autoFocus={!first} />
          </label>
          {first && (
            <label className="field">
              <span className="field-label">Same again</span>
              <input className="input" type="password" value={again} onChange={(e) => setAgain(e.target.value)}
                autoComplete="new-password" />
            </label>
          )}
          <div className="gate-error" role="alert">{error}</div>
          <button className="btn primary wide" disabled={busy || !password || (first && (!code || !again))}>
            {busy ? <span className="spinner" /> : null}
            {first ? 'Set password and sign in' : 'Sign in'}
          </button>
        </form>
        {!first && <div className="gate-foot">VibeStream</div>}
      </div>
    </div>
  )
}

function Shell({ onOut }) {
  const [page, setPage] = useState(pageFromPath)
  const [open, setOpen] = useState(false)
  const [problems, setProblems] = useState(0)
  const [version, setVersion] = useState('')

  useEffect(() => {
    const back = () => setPage(pageFromPath())
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])

  useEffect(() => {
    admin.overview().then((o) => {
      setProblems(o.problems_24h || 0)
      setVersion(o.version || '')
    }).catch(() => {})
  }, [page])

  const go = (id) => {
    if (id !== page) window.history.pushState(null, '', id === 'overview' ? '/admin' : `/admin/${id}`)
    setPage(id)
    setOpen(false)
    window.scrollTo(0, 0)
  }

  const signOut = async () => {
    try { await admin.signOut() } catch { /* gone either way */ }
    onOut()
  }

  const { Page } = PAGES.find((p) => p.id === page)
  return (
    <div className="shell">
      <aside className={`rail ${open ? 'open' : ''}`}>
        <div className="brand">
          <VMark size={24} />
          <Wordmark size={13} className="brand-word" />
          <span className="brand-tag">Admin</span>
          <button className="btn quiet small rail-toggle" onClick={() => setOpen(!open)} aria-label="Menu">
            <Icon name={open ? 'close' : 'list'} size={18} />
          </button>
        </div>
        <nav className="nav">
          {PAGES.map((p) => (p.group ? (
            <div className="nav-group" key={p.group}>{p.group}</div>
          ) : (
            <a key={p.id} href={p.id === 'overview' ? '/admin' : `/admin/${p.id}`}
              className={page === p.id ? 'on' : ''}
              onClick={(e) => { e.preventDefault(); go(p.id) }}>
              <Icon name={p.icon} size={18} />
              {p.label}
              {p.id === 'activity' && problems > 0 && <span className="nav-count">{problems}</span>}
            </a>
          )))}
        </nav>
        <div className="rail-foot">
          <div className="rail-server"><span className="dot good" /> {window.location.host}{version ? ` · ${version}` : ''}</div>
          <button className="btn" onClick={signOut}><Icon name="exit" size={16} /> Sign out</button>
        </div>
      </aside>
      <main className="page">
        <Page go={go} />
      </main>
      <SaveBar />
    </div>
  )
}
